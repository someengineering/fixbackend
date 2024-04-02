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
from datetime import datetime, timedelta

from fixcloudutils.util import utc
from sqlalchemy import text

from fixbackend.auth.models.orm import User
from fixbackend.ids import UserId
from fixbackend.notification.email.scheduled_email import (
    ScheduledEmailSender,
    ScheduledEmailEntity,
    ScheduledEmailSentEntity,
)
from fixbackend.notification.user_notification_repo import UserNotificationSettingsRepositoryImpl
from fixbackend.types import AsyncSessionMaker
from fixbackend.utils import uid
from tests.fixbackend.conftest import InMemoryEmailSender


async def test_scheduled_emails(email_sender: InMemoryEmailSender, async_session_maker: AsyncSessionMaker) -> None:
    sender = ScheduledEmailSender(email_sender, async_session_maker)
    pref = UserNotificationSettingsRepositoryImpl(async_session_maker)
    now = utc()

    async with async_session_maker() as session:

        def create_user(name: str, at: datetime) -> User:
            user = User(
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
            # session.commit()
            return user

        def email_send(user: User, *kinds: str) -> None:
            for kind in kinds:
                sent = ScheduledEmailSentEntity(id=uid(), user_id=user.id, kind=kind, at=now)
                session.add(sent)
            # session.commit()

        # noinspection SqlWithoutWhere
        await session.execute(text("DELETE FROM scheduled_email"))
        session.add(ScheduledEmailEntity(id=uid(), kind="day1", after=timedelta(days=1).total_seconds()))
        session.add(ScheduledEmailEntity(id=uid(), kind="day2", after=timedelta(days=2).total_seconds()))
        session.add(ScheduledEmailEntity(id=uid(), kind="day3", after=timedelta(days=3).total_seconds()))
        session.add(ScheduledEmailEntity(id=uid(), kind="day4", after=timedelta(days=4).total_seconds()))
        session.add(ScheduledEmailEntity(id=uid(), kind="day5", after=timedelta(days=5).total_seconds()))
        await session.commit()

        # user a signed up 100 days ago. He will receive 5 emails
        a = create_user("a", now - timedelta(days=100, hours=1))
        email_send(a, "day1", "day2", "day3", "day4")
        await sender._send_emails()
        assert len(email_sender.call_args) == 1
        email_sender.call_args.clear()

        # user b signed up 5 days ago. He will also receive 5 emails
        b = create_user("b", now - timedelta(days=5, hours=1))
        email_send(b, "day1", "day2")
        await sender._send_emails()
        assert len(email_sender.call_args) == 3
        email_sender.call_args.clear()

        # user c signed up 3 days ago. He will receive 3 emails
        c = create_user("c", now - timedelta(days=3, hours=1))
        email_send(c, "day1", "day2", "day3")
        await sender._send_emails()
        assert len(email_sender.call_args) == 0
        email_sender.call_args.clear()

        # user d signed up 4 days ago and already received 2 emails. He will receive 2 emails
        d = create_user("d", now - timedelta(days=4, hours=1))
        email_send(d, "day1", "day2")
        await sender._send_emails()
        assert len(email_sender.call_args) == 2
        email_sender.call_args.clear()

        # user e signed up 5 days ago and opted out of emails. He will receive 0 emails
        e = create_user("e", now - timedelta(days=5, hours=1))
        await pref.update_notification_settings(UserId(e.id), tutorial=False)
        await sender._send_emails()
        assert len(email_sender.call_args) == 0
