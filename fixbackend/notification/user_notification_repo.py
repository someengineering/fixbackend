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
#  along with this program.  If not, see <http://www.gnu.org/licenses/>

import uuid
from abc import ABC, abstractmethod
from typing import Annotated, override, Optional

from attr import frozen
from fastapi import Depends
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import Boolean, select
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.auth.models.orm import User
from fixbackend.base_model import Base, CreatedUpdatedMixin
from fixbackend.dependencies import FixDependency, ServiceNames
from fixbackend.ids import UserId, Email
from fixbackend.types import AsyncSessionMaker


@frozen
class UserNotificationSettings:
    user_id: UserId
    weekly_report: bool
    inactivity_reminder: bool
    tutorial: bool


class UserNotificationSettingsEntity(CreatedUpdatedMixin, Base):
    __tablename__ = "user_notification_settings"

    user_id: Mapped[UserId] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    weekly_report: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    inactivity_reminder: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tutorial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def to_model(self) -> UserNotificationSettings:
        return UserNotificationSettings(
            user_id=self.user_id,
            weekly_report=self.weekly_report,
            inactivity_reminder=self.inactivity_reminder,
            tutorial=self.tutorial,
        )

    @staticmethod
    def from_model(settings: UserNotificationSettings) -> "UserNotificationSettingsEntity":
        return UserNotificationSettingsEntity(
            user_id=settings.user_id,
            weekly_report=settings.weekly_report,
            inactivity_reminder=settings.inactivity_reminder,
            tutorial=settings.tutorial,
        )


class UserNotificationSettingsRepository(ABC):
    @abstractmethod
    async def get_notification_settings(self, user_id: UserId) -> UserNotificationSettings:
        pass

    @abstractmethod
    async def update_notification_settings(
        self,
        user_id_or_email: UserId | Email,
        *,
        weekly_report: Optional[bool] = None,
        inactivity_reminder: Optional[bool] = None,
        tutorial: Optional[bool] = None,
    ) -> UserNotificationSettings:
        pass


class UserNotificationSettingsRepositoryImpl(UserNotificationSettingsRepository):

    def __init__(self, session_maker: AsyncSessionMaker) -> None:
        self.session_maker = session_maker

    @override
    async def get_notification_settings(self, user_id: UserId) -> UserNotificationSettings:
        async with self.session_maker() as session:
            if result := await session.get(UserNotificationSettingsEntity, user_id):
                return result.to_model()
            else:
                return UserNotificationSettings(
                    user_id=user_id, weekly_report=True, inactivity_reminder=True, tutorial=True
                )

    @override
    async def update_notification_settings(
        self,
        user_id_or_email: UserId | Email,
        *,
        weekly_report: Optional[bool] = None,
        inactivity_reminder: Optional[bool] = None,
        tutorial: Optional[bool] = None,
    ) -> UserNotificationSettings:
        async with self.session_maker() as session:
            if isinstance(user_id_or_email, str):
                maybe_user = (
                    await session.execute(select(User).where(User.email == user_id_or_email))  # type: ignore
                ).scalar_one_or_none()
                if maybe_user is None:
                    raise ValueError("User not found")
                user_id = maybe_user.id
            else:
                user_id = user_id_or_email
            value = await session.get(UserNotificationSettingsEntity, user_id)
            if value is None:
                value = UserNotificationSettingsEntity(
                    user_id=user_id, weekly_report=True, inactivity_reminder=True, tutorial=True
                )
                session.add(value)
            if weekly_report is not None:
                value.weekly_report = weekly_report
            if inactivity_reminder is not None:
                value.inactivity_reminder = inactivity_reminder
            if tutorial is not None:
                value.tutorial = tutorial
            settings = value.to_model()
            await session.commit()
            return settings


def get_user_notification_settings_repo(
    fix_dependency: FixDependency,
) -> UserNotificationSettingsRepository:
    return fix_dependency.service(
        ServiceNames.user_notification_settings_repository, UserNotificationSettingsRepositoryImpl
    )


UserNotificationSettingsRepositoryDependency = Annotated[
    UserNotificationSettingsRepository, Depends(get_user_notification_settings_repo)
]
