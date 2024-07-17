#  Copyright (c) 2024. Some Engineering
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
from datetime import datetime, timedelta, timezone

import pytest
from fixcloudutils.asyncio.process_pool import AsyncProcessPool
from fixcloudutils.util import utc
from sqlalchemy import text

from fixbackend.auth.models import User
from fixbackend.auth.models.orm import User as OrmUser
from fixbackend.config import Config
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import UserId, ProductTier
from fixbackend.inventory.inventory_client import InventoryClient
from fixbackend.inventory.inventory_service import InventoryService
from fixbackend.notification.email.scheduled_email import (
    ScheduledEmailSender,
    ScheduledEmailEntity,
    ScheduledEmailSentEntity,
)
from fixbackend.notification.email.status_update_email_creator import StatusUpdateEmailCreator
from fixbackend.notification.user_notification_repo import UserNotificationSettingsRepositoryImpl
from fixbackend.types import AsyncSessionMaker
from fixbackend.utils import uid
from fixbackend.workspaces.repository import WorkspaceRepository
from tests.fixbackend.conftest import InMemoryEmailSender
from tests.fixbackend.inventory.inventory_client_test import mocked_inventory_client  # noqa


@pytest.fixture
async def scheduled_email_sender(
    default_config: Config,
    email_sender: InMemoryEmailSender,
    async_session_maker: AsyncSessionMaker,
    inventory_service: InventoryService,
    graph_database_access_manager: GraphDatabaseAccessManager,
    async_process_pool: AsyncProcessPool,
    mocked_inventory_client: InventoryClient,  # noqa
) -> ScheduledEmailSender:

    return ScheduledEmailSender(
        default_config,
        email_sender,
        async_session_maker,
        StatusUpdateEmailCreator(inventory_service, graph_database_access_manager, async_process_pool),
    )


# noinspection SqlWithoutWhere
async def test_scheduled_emails(
    scheduled_email_sender: ScheduledEmailSender,
    email_sender: InMemoryEmailSender,
    async_session_maker: AsyncSessionMaker,
) -> None:
    pref = UserNotificationSettingsRepositoryImpl(async_session_maker)
    now = utc()

    async with async_session_maker() as session:

        def create_user(name: str, at: datetime) -> OrmUser:
            user = OrmUser(
                id=uid(),
                email=name,
                hashed_password="password",
                is_active=True,
                is_superuser=False,
                is_verified=True,
                created_at=at,
                updated_at=at,
            )
            session.add(user)
            return user

        def email_send(user: OrmUser, *kinds: str) -> None:
            for kind in kinds:
                sent = ScheduledEmailSentEntity(id=uid(), user_id=user.id, kind=kind, at=now)
                session.add(sent)
            # session.commit()

        await session.execute(text("DELETE FROM scheduled_email"))
        await session.execute(text("DELETE FROM scheduled_email_sent"))
        session.add(ScheduledEmailEntity(id=uid(), kind="day1", after=timedelta(days=1).total_seconds()))
        session.add(ScheduledEmailEntity(id=uid(), kind="day2", after=timedelta(days=2).total_seconds()))
        session.add(ScheduledEmailEntity(id=uid(), kind="day3", after=timedelta(days=3).total_seconds()))
        session.add(ScheduledEmailEntity(id=uid(), kind="day4", after=timedelta(days=4).total_seconds()))
        session.add(ScheduledEmailEntity(id=uid(), kind="day5", after=timedelta(days=5).total_seconds()))
        await session.commit()

        # user a signed up 100 days ago. He will receive 5 emails
        a = create_user("a", now - timedelta(days=100, hours=1))
        email_send(a, "day1", "day2", "day3", "day4")
        await scheduled_email_sender._send_scheduled_emails()
        assert len(email_sender.call_args) == 1
        email_sender.call_args.clear()

        # user b signed up 5 days ago. He will also receive 5 emails
        b = create_user("b", now - timedelta(days=5, hours=1))
        email_send(b, "day1", "day2")
        await scheduled_email_sender._send_scheduled_emails()
        assert len(email_sender.call_args) == 3
        email_sender.call_args.clear()

        # user c signed up 3 days ago. He will receive 3 emails
        c = create_user("c", now - timedelta(days=3, hours=1))
        email_send(c, "day1", "day2", "day3")
        await scheduled_email_sender._send_scheduled_emails()
        assert len(email_sender.call_args) == 0
        email_sender.call_args.clear()

        # user d signed up 4 days ago and already received 2 emails. He will receive 2 emails
        d = create_user("d", now - timedelta(days=4, hours=1))
        email_send(d, "day1", "day2")
        await scheduled_email_sender._send_scheduled_emails()
        assert len(email_sender.call_args) == 2
        email_sender.call_args.clear()

        # user e signed up 5 days ago and opted out of emails. He will receive 0 emails
        e = create_user("e", now - timedelta(days=5, hours=1))
        await pref.update_notification_settings(UserId(e.id), tutorial=False)
        await scheduled_email_sender._send_scheduled_emails()
        assert len(email_sender.call_args) == 0


# noinspection SqlWithoutWhere
async def test_new_workspaces_without_cloud_account(
    scheduled_email_sender: ScheduledEmailSender,
    email_sender: InMemoryEmailSender,
    async_session_maker: AsyncSessionMaker,
    workspace_repository: WorkspaceRepository,
    user: User,
) -> None:
    async with async_session_maker() as session:
        await workspace_repository.create_workspace("some_new", "some_new", user)
        # adjust the created time of the workspace
        await session.execute(
            text("UPDATE organization SET created_at = :created_at").bindparams(
                created_at=utc() - timedelta(days=1, hours=1)
            )
        )
        await session.execute(text("DELETE FROM scheduled_email"))
        await session.execute(text("DELETE FROM scheduled_email_sent"))
        await scheduled_email_sender._new_workspaces_without_cloud_account(utc())
        assert len(email_sender.call_args) == 1
        email_sender.call_args.clear()
        await scheduled_email_sender._new_workspaces_without_cloud_account(utc())
        assert len(email_sender.call_args) == 0


# noinspection SqlWithoutWhere
async def test_scheduled_updates(
    scheduled_email_sender: ScheduledEmailSender,
    email_sender: InMemoryEmailSender,
    async_session_maker: AsyncSessionMaker,
    workspace_repository: WorkspaceRepository,
    user: User,
) -> None:

    first_sunday_of_month = datetime(2024, 4, 7, hour=10, tzinfo=timezone.utc)  # wednesday
    middle_of_the_month = datetime(2024, 4, 24, tzinfo=timezone.utc)  # wednesday
    sunday = datetime(2024, 4, 28, hour=10, tzinfo=timezone.utc)  # wednesday

    async with async_session_maker() as session:

        async def clear() -> None:
            email_sender.call_args.clear()
            await session.execute(text("DELETE FROM scheduled_email"))
            await session.execute(text("DELETE FROM scheduled_email_sent"))

        big_corp = await workspace_repository.create_workspace("big_corp", "big_corp", user)
        free_corp = await workspace_repository.create_workspace("free_corp", "free_corp", user)
        update = text("UPDATE organization SET tier=:tier WHERE name=:name")
        await session.execute(update.bindparams(tier=ProductTier.Free, name=free_corp.name))
        await session.execute(update.bindparams(tier=ProductTier.Enterprise, name=big_corp.name))

        # the account should be older than a month
        await session.execute(
            text("UPDATE organization SET created_at = :created_at").bindparams(created_at=utc() - timedelta(days=128))
        )

        # nothing is sent
        await clear()
        sent = await scheduled_email_sender._send_scheduled_status_update(middle_of_the_month)
        assert sent == 0  # no email is sent, since not a Friday and no start of month

        # first sunday of the month: big_corp and free_corp receive an email
        await clear()
        sent = await scheduled_email_sender._send_scheduled_status_update(first_sunday_of_month)
        assert sent == 2
        # email to big_corp
        assert email_sender.call_args[0].to == user.email
        assert "weekly" in email_sender.call_args[0].subject
        assert 'Workspace: "big_corp"' in email_sender.call_args[0].text
        assert "/api/analytics/email_opened/pixel" in email_sender.call_args[0].html  # type: ignore
        # email to free_corp
        assert email_sender.call_args[1].to == user.email
        assert "monthly" in email_sender.call_args[1].subject
        assert 'Workspace: "free_corp"' in email_sender.call_args[1].text
        assert "/api/analytics/email_opened/pixel" in email_sender.call_args[1].html  # type: ignore
        # doing it again does not send another email
        sent = await scheduled_email_sender._send_scheduled_status_update(first_sunday_of_month)
        assert sent == 0

        # every other sunday: only big_corp will receive a status update
        await clear()
        sent = await scheduled_email_sender._send_scheduled_status_update(sunday)
        assert sent == 1
        assert email_sender.call_args[0].to == user.email
        assert "weekly" in email_sender.call_args[0].subject
        assert 'Workspace: "big_corp"' in email_sender.call_args[0].text
        assert "/api/analytics/email_opened/pixel" in email_sender.call_args[0].html  # type: ignore
        # doing it again does not send another email
        sent = await scheduled_email_sender._send_scheduled_status_update(sunday)
        assert sent == 0
