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


import asyncio
import logging
from datetime import datetime, timedelta
from enum import StrEnum
from typing import List, Optional

from attrs import frozen
from fastapi_users_db_sqlalchemy.generics import GUID
from fixcloudutils.asyncio.periodic import Periodic
from fixcloudutils.service import Service
from fixcloudutils.util import utc
from sqlalchemy import String, Text, or_, select
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.auth.user_repository import UserRepository
from fixbackend.base_model import Base
from fixbackend.ids import OneTimeEmailId, UserId, WorkspaceId
from fixbackend.notification.email.email_messages import EmailMessage
from fixbackend.notification.notification_service import NotificationService
from fixbackend.sqlalechemy_extensions import UTCDateTime
from fixbackend.types import AsyncSessionMaker
from fixbackend.utils import uid

log = logging.getLogger(__name__)


class OneTimeEmailKind(StrEnum):
    TrialEndNotification = "trial_end"


@frozen
class OneTimeEmail:
    id: OneTimeEmailId
    kind: OneTimeEmailKind
    user_id: Optional[UserId]
    workspace_id: Optional[WorkspaceId]
    subject: str
    text_content: str
    html_content: Optional[str]
    scheduled_at: datetime
    sent_at: Optional[datetime]


class OneTimeEmailEntity(Base):
    __tablename__ = "fire_and_forget_email"
    id: Mapped[OneTimeEmailId] = mapped_column(GUID, primary_key=True)
    kind: Mapped[str] = mapped_column(String(length=256), nullable=False)
    user_id: Mapped[UserId] = mapped_column(GUID, nullable=True, index=True)
    workspace_id: Mapped[WorkspaceId] = mapped_column(GUID, nullable=True, index=True)
    subject: Mapped[str] = mapped_column(String(length=1024), nullable=False)
    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    html_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True, index=True)

    def to_model(self) -> OneTimeEmail:
        return OneTimeEmail(
            id=self.id,
            kind=OneTimeEmailKind(self.kind),
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            subject=self.subject,
            text_content=self.text_content,
            html_content=self.html_content,
            scheduled_at=self.scheduled_at,
            sent_at=self.sent_at,
        )

    @staticmethod
    def from_model(model: OneTimeEmail) -> "OneTimeEmailEntity":

        return OneTimeEmailEntity(
            id=model.id,
            kind=model.kind.value,
            user_id=model.user_id,
            workspace_id=model.workspace_id,
            subject=model.subject,
            text_content=model.text_content,
            html_content=model.html_content,
            scheduled_at=model.scheduled_at,
            sent_at=model.sent_at,
        )


class OneTimeEmailService(Service):
    def __init__(
        self,
        notification_service: NotificationService,
        user_repository: UserRepository,
        session_maker: AsyncSessionMaker,
        dispatching: bool,
    ) -> None:
        self.session_maker = session_maker
        self.notification_service = notification_service
        self.user_repository = user_repository
        self._send_pending_emails: Optional[Periodic] = None
        self._cleanup_old_emails: Optional[Periodic] = None

        if dispatching:
            self._send_pending_emails = Periodic("send_pending_emails", self._send_emails_job, timedelta(minutes=1))
            self._cleanup_old_emails = Periodic("cleanup_old_emails", self._cleanup_old_emails_job, timedelta(days=1))

    async def start(self) -> None:
        if self._send_pending_emails:
            await self._send_pending_emails.start()
        if self._cleanup_old_emails:
            await self._cleanup_old_emails.start()

    async def stop(self) -> None:
        if self._cleanup_old_emails:
            await self._cleanup_old_emails.stop()
        if self._send_pending_emails:
            await self._send_pending_emails.stop()

    async def _send_emails_job(self) -> None:
        pending_emails = await self.list_pending_emails()
        async with asyncio.TaskGroup() as tg:
            for email in pending_emails:
                tg.create_task(self._send_pending_email(email))

    async def list_pending_emails(self) -> List[OneTimeEmail]:
        async with self.session_maker() as session:
            async with session.begin():
                statement = (
                    select(OneTimeEmailEntity)
                    .where(OneTimeEmailEntity.sent_at == None)  # noqa
                    .where(OneTimeEmailEntity.scheduled_at <= utc())
                )
                result = await session.execute(statement)
                return [email.to_model() for email in result.scalars()]

    async def _send_pending_email(self, to_send: OneTimeEmail) -> None:
        async with self.session_maker() as session:
            entity = await session.get(OneTimeEmailEntity, to_send.id)
            if entity:
                try:
                    if to_send.user_id:
                        user = await self.user_repository.get(to_send.user_id)
                        if user:
                            await self.notification_service.send_email(
                                to=user.email,
                                subject=entity.subject,
                                text=entity.text_content,
                                html=entity.html_content,
                            )
                    if to_send.workspace_id:
                        await self.notification_service.send_email_to_workspace(
                            workspace_id=to_send.workspace_id,
                            subject=entity.subject,
                            text=entity.text_content,
                            html=entity.html_content,
                        )

                    entity.sent_at = utc()
                    session.add(entity)
                    await session.commit()
                except Exception as e:
                    log.warning(f"Error sending email {to_send.id}: {e}")
                    await session.rollback()

    async def schedule_one_time_email(
        self,
        *,
        kind: OneTimeEmailKind,
        scheduled_at: datetime,
        user_id: Optional[UserId],
        workspace_id: Optional[WorkspaceId],
        message: EmailMessage,
    ) -> OneTimeEmail:
        if not user_id and not workspace_id:
            raise ValueError("Either user_id or workspace_id must be provided")

        if user_id and workspace_id:
            raise ValueError("Only one of user_id or workspace_id can be provided")

        model = OneTimeEmail(
            id=OneTimeEmailId(uid()),
            kind=kind,
            user_id=user_id,
            workspace_id=workspace_id,
            subject=message.subject(),
            text_content=message.text(),
            html_content=message.html(),
            scheduled_at=scheduled_at,
            sent_at=None,
        )
        async with self.session_maker() as session:
            async with session.begin():
                entity = OneTimeEmailEntity.from_model(model)
                session.add(entity)
                await session.commit()
                return model

    async def unschedule_one_time_email(
        self, user_id: Optional[UserId], workspace_id: Optional[WorkspaceId], kind: OneTimeEmailKind
    ) -> None:
        if not user_id and not workspace_id:
            raise ValueError("Either user_id or workspace_id must be provided")

        async with self.session_maker() as session:
            statement = (
                select(OneTimeEmailEntity)
                .where(OneTimeEmailEntity.kind == kind.value)
                .where(or_(OneTimeEmailEntity.user_id == user_id, OneTimeEmailEntity.workspace_id == workspace_id))
            )
            result = await session.execute(statement)
            for email in result.scalars():
                await session.delete(email)
            await session.commit()

    async def _cleanup_old_emails_job(self) -> None:
        async with self.session_maker() as session:
            async with session.begin():
                statement = (
                    select(OneTimeEmailEntity)
                    .where(OneTimeEmailEntity.sent_at != None)  # noqa
                    .where(OneTimeEmailEntity.sent_at < utc() - timedelta(days=30))
                )
                result = (await session.execute(statement)).unique().scalars()

                for old_email in result:
                    await session.delete(old_email)

                await session.commit()
