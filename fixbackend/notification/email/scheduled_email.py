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
import calendar
import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict, Set, Callable
from uuid import UUID

from fastapi_users_db_sqlalchemy.generics import GUID
from fixcloudutils.asyncio.periodic import Periodic
from fixcloudutils.service import Service
from fixcloudutils.util import utc
from sqlalchemy import String, Integer, select, Index, and_, or_, func, text, Select, ColumnExpressionArgument
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import INTERVAL

from fixbackend.auth.models.orm import User
from fixbackend.auth.models import User as UserModel
from fixbackend.base_model import Base
from fixbackend.cloud_accounts.models.orm import CloudAccount
from fixbackend.config import Config
from fixbackend.ids import WorkspaceId, ProductTier
from fixbackend.inventory.inventory_client import NoSuchGraph, GraphDatabaseNotAvailable
from fixbackend.notification.email import email_messages
from fixbackend.notification.email.email_sender import EmailSender
from fixbackend.notification.email.status_update_email_creator import StatusUpdateEmailCreator
from fixbackend.notification.user_notification_repo import UserNotificationSettingsEntity
from fixbackend.sqlalechemy_extensions import UTCDateTime
from fixbackend.types import AsyncSessionMaker
from fixbackend.utils import uid
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.models.orm import Organization, OrganizationMembers

log = logging.getLogger(__name__)
no_cloud_account = "no_cloud_account"


class ScheduledEmailEntity(Base):
    __tablename__ = "scheduled_email"
    id: Mapped[UUID] = mapped_column(GUID, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    after: Mapped[int] = mapped_column(Integer, nullable=False)


class ScheduledEmailSentEntity(Base):
    __tablename__ = "scheduled_email_sent"
    id: Mapped[UUID] = mapped_column(GUID, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(GUID, nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    user_kind_index = Index("user_kind_index", "user_id", "kind")


class ScheduledEmailSender(Service):
    def __init__(
        self,
        config: Config,
        email_sender: EmailSender,
        session_maker: AsyncSessionMaker,
        status_update_creator: StatusUpdateEmailCreator,
    ) -> None:
        self.config = config
        self.email_sender = email_sender
        self.session_maker = session_maker
        self.status_update_creator = status_update_creator
        self.periodic = Periodic("scheduled_email_sender", self._send_emails, timedelta(seconds=600))

    async def start(self) -> None:
        await self.periodic.start()

    async def stop(self) -> None:
        await self.periodic.stop()

    async def _send_emails(self) -> None:
        now = utc()
        await self._new_workspaces_without_cloud_account(now)
        await self._send_scheduled_status_update(now)
        await self._send_scheduled_emails()

    async def _send_scheduled_status_update(self, now: datetime) -> int:
        counter = 0

        async def send_emails(kind: str, duration: timedelta, email_filter: ColumnExpressionArgument[bool]) -> None:
            nonlocal counter
            unique_id = f'update-{kind}-{now.strftime("%y%m%d")}'  # valid for the whole day
            users_already_marked: Set[UUID] = set()
            statement = (
                (select(Organization, User))
                .join(OrganizationMembers, Organization.id == OrganizationMembers.organization_id)
                .join(User, OrganizationMembers.user_id == User.id)
                .outerjoin(UserNotificationSettingsEntity, User.id == UserNotificationSettingsEntity.user_id)  # type: ignore # noqa
                .outerjoin(
                    ScheduledEmailSentEntity,
                    and_(
                        User.id == ScheduledEmailSentEntity.user_id,  # type: ignore
                        ScheduledEmailSentEntity.kind == unique_id,
                    ),
                )
                .where(
                    and_(
                        email_filter,
                        Organization.created_at < (now - duration),  # org is older than min age
                        ScheduledEmailSentEntity.id.is_(None),  # user has not received this email yet
                        or_(
                            UserNotificationSettingsEntity.weekly_report.is_(None),  # no setting
                            UserNotificationSettingsEntity.weekly_report.is_(True),  # setting, not opted out
                        ),
                    )
                )
                .order_by(Organization.id, User.id)  # type: ignore
            )
            async with self.session_maker() as session:
                last_workspace: Optional[Workspace] = None
                send_fn: Optional[Callable[[UserModel], Tuple[str, str, str, Dict[str, bytes]]]] = None
                for org, orm_user in (await session.execute(statement)).unique().all():
                    user = orm_user.to_model()
                    workspace: Workspace = org.to_model()
                    try:
                        if last_workspace != workspace:
                            send_fn = await self.status_update_creator.create_messages_fn(workspace, now, duration)
                        assert send_fn is not None, "Send function not set for workspace"
                        subject, html, txt, images = send_fn(user)
                        await self.email_sender.send_email(
                            to=user.email,
                            subject=subject,
                            text=txt,
                            html=html,
                            unsubscribe=UserNotificationSettingsEntity.weekly_report.name,
                            images=images,
                        )
                        log.info(
                            f"Sent status update email={user.email}, workspace={workspace.id}, "
                            f"tier={workspace.current_product_tier()}, subject: {subject}"
                        )
                        # Only add the user once for this update.
                        # If the user is in multiple workspaces, they will get multiple emails.
                        if user.id not in users_already_marked:
                            session.add(ScheduledEmailSentEntity(id=uid(), user_id=user.id, kind=unique_id, at=now))
                            users_already_marked.add(user.id)
                        counter += 1
                    except GraphDatabaseNotAvailable:
                        pass  # ignore workspaces without graphs
                    except NoSuchGraph:
                        pass  # ignore workspaces without graphs
                    except Exception:
                        log.exception(f"Failed to send status update email for workspace {workspace.id}", exc_info=True)
                await session.commit()

        # Create a status update email for all support users for testing
        if now.weekday() == 4 and 7 <= now.hour <= 8:  # Every Friday
            await send_emails("test", timedelta(days=7), User.email.in_(self.config.customer_support_users))  # type: ignore # noqa

        if now.weekday() == 6 and 9 <= now.hour <= 12:  # Every Sunday
            await send_emails("week", timedelta(days=7), Organization.tier != ProductTier.Free)

        if now.weekday() == 6 and now.day <= 7 and 9 <= now.hour <= 12:  # 1st sunday of the month
            ten_days_ago = now - timedelta(days=10)
            _, days_of_last_month = calendar.monthrange(ten_days_ago.year, ten_days_ago.month)
            await send_emails("month", timedelta(days=days_of_last_month), Organization.tier == ProductTier.Free)

        return counter

    async def _new_workspaces_without_cloud_account(self, now: datetime) -> None:
        async with self.session_maker() as session:
            # select all workspaces
            stmt: Select[Tuple[WorkspaceId]] = (
                select(Organization.id)
                .outerjoin(CloudAccount, CloudAccount.tenant_id == Organization.id)
                .where(
                    and_(
                        CloudAccount.id.is_(None),  # do not have a cloud account
                        Organization.created_at < (now - timedelta(days=1)),  # created more than a day ago
                        Organization.created_at > (now - timedelta(days=2)),  # created less than two days ago
                    )
                )
            )
            workspace_ids = (await session.execute(stmt)).scalars().all()

            # bail out early if there are no workspaces to process
            if len(workspace_ids) == 0:
                return

            query = (
                select(User)
                .join(
                    OrganizationMembers,
                    and_(
                        User.id == OrganizationMembers.user_id,  # type: ignore
                        OrganizationMembers.organization_id.in_(workspace_ids),
                    ),
                )
                .outerjoin(
                    ScheduledEmailSentEntity,
                    and_(
                        User.id == ScheduledEmailSentEntity.user_id,  # type: ignore
                        ScheduledEmailSentEntity.kind == no_cloud_account,
                    ),
                )
                .where(ScheduledEmailSentEntity.id.is_(None))
            )

            # send the email to all users that have not received it yet
            all_users = (await session.execute(query)).unique().scalars().all()
            for user in all_users:
                subject = "Fix: Connect your Cloud Accounts  🔌"
                txt = email_messages.render("no_cloud_account.txt")
                html = email_messages.render("no_cloud_account.html", user_id=user.id)
                log.info(f"Sending email to {user.email} with subject {subject}.")
                await self.email_sender.send_email(to=user.email, subject=subject, text=txt, html=html)
                session.add(ScheduledEmailSentEntity(id=uid(), user_id=user.id, kind=no_cloud_account, at=now))
            await session.commit()

    async def _send_scheduled_emails(self) -> None:
        async with self.session_maker() as session:
            stmt = (
                select(User, ScheduledEmailEntity)
                .select_from(
                    # This uses a literal TRUE to simulate a cross-join
                    User.__table__.join(ScheduledEmailEntity.__table__, text("true"))
                )
                .outerjoin(
                    ScheduledEmailSentEntity,
                    and_(
                        User.id == ScheduledEmailSentEntity.user_id,  # type: ignore
                        ScheduledEmailEntity.kind == ScheduledEmailSentEntity.kind,
                    ),
                )
                .outerjoin(
                    UserNotificationSettingsEntity,
                    and_(
                        UserNotificationSettingsEntity.user_id == User.id,
                        UserNotificationSettingsEntity.tutorial == False,  # noqa
                    ),
                )
                .where(
                    and_(
                        User.created_at
                        + func.cast(func.cast(ScheduledEmailEntity.after, String) + " seconds", INTERVAL)
                        < func.now(),
                        ScheduledEmailSentEntity.id.is_(None),
                        UserNotificationSettingsEntity.user_id.is_(None),
                    )
                )
            )
            result = await session.execute(stmt)
            user: User
            to_send: ScheduledEmailEntity
            for user, to_send in result.unique().all():
                subject = email_messages.render(f"{to_send.kind}.subject").strip()
                txt = email_messages.render(f"{to_send.kind}.txt")
                html = email_messages.render(f"{to_send.kind}.html", user_id=user.id)
                log.info(f"Sending email to {user.email} with subject {subject}")
                await self.email_sender.send_email(
                    to=user.email, subject=subject, text=txt, html=html, unsubscribe="tutorial"
                )
                # mark this kind of email as sent
                session.add(ScheduledEmailSentEntity(id=uid(), user_id=user.id, kind=to_send.kind, at=utc()))
            await session.commit()
