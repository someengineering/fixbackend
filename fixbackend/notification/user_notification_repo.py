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

from abc import ABC, abstractmethod
from typing import Annotated, override

from fastapi import Depends
from fixbackend.db import AsyncSessionMakerDependency

from fixbackend.ids import UserId
from fixbackend.types import AsyncSessionMaker

import uuid


from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import Boolean
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.base_model import Base

from attr import frozen


@frozen
class UserNotificationSettings:
    user_id: UserId
    weekly_report: bool
    inactivity_reminder: bool


class UserNotificationSettingsEntity(Base):
    __tablename__ = "user_notification_settings"

    user_id: Mapped[UserId] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    weekly_report: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    inactivity_reminder: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def to_model(self) -> UserNotificationSettings:
        return UserNotificationSettings(
            user_id=self.user_id,
            weekly_report=self.weekly_report,
            inactivity_reminder=self.inactivity_reminder,
        )

    @staticmethod
    def from_model(settings: UserNotificationSettings) -> "UserNotificationSettingsEntity":
        return UserNotificationSettingsEntity(
            user_id=settings.user_id,
            weekly_report=settings.weekly_report,
            inactivity_reminder=settings.inactivity_reminder,
        )


class UserNotificationSettingsRepository(ABC):
    @abstractmethod
    async def get_notification_settings(self, user_id: UserId) -> UserNotificationSettings:
        pass

    @abstractmethod
    async def update_notification_settings(
        self, user_id: UserId, settings: UserNotificationSettings
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
                    user_id=user_id,
                    weekly_report=True,
                    inactivity_reminder=False,
                )

    @override
    async def update_notification_settings(
        self, user_id: UserId, settings: UserNotificationSettings
    ) -> UserNotificationSettings:
        async with self.session_maker() as session:
            existing = await session.get(UserNotificationSettingsEntity, user_id)
            if existing:
                existing.weekly_report = settings.weekly_report
                existing.inactivity_reminder = settings.inactivity_reminder
            else:
                new = UserNotificationSettingsEntity.from_model(settings)
                session.add(new)

            await session.commit()
            return settings


def get_user_notification_settings_repo(
    session_maker: AsyncSessionMakerDependency,
) -> UserNotificationSettingsRepository:
    return UserNotificationSettingsRepositoryImpl(session_maker)


UserNotificationSettingsReporitoryDependency = Annotated[
    UserNotificationSettingsRepository, Depends(get_user_notification_settings_repo)
]
