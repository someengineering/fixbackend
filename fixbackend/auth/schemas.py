#  Copyright (c) 2023. Some Engineering
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

import uuid
from pydantic import BaseModel, Field
from fastapi_users import schemas
from fixbackend.ids import UserId

from fixbackend.notification.user_notification_repo import UserNotificationSettings


class UserRead(schemas.BaseUser[uuid.UUID]):
    is_mfa_active: bool = Field(description="Whether MFA is active")


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    pass


class OAuthProviderAuthUrl(BaseModel):
    name: str = Field(description="Name of the OAuth provider")
    authUrl: str = Field(description="URL to initiate auth flow")


class OAuthProviderAssociateUrl(BaseModel):
    name: str = Field(description="Name of the OAuth provider")
    associated: bool = Field(description="Whether the user is already associated with this provider")
    account_id: uuid.UUID | None = Field(description="ID of the OAuth account, if associated")
    account_email: str | None = Field(description="Email of the user if already associated")
    authUrl: str = Field(description="URL to initiate association flow")


class UserNotificationSettingsRead(BaseModel):
    weekly_report: bool = Field(description="Whether to send a weekly report")
    inactivity_reminder: bool = Field(description="Whether to send a reminder for open incidents")

    @staticmethod
    def from_model(model: UserNotificationSettings) -> "UserNotificationSettingsRead":
        return UserNotificationSettingsRead(
            weekly_report=model.weekly_report,
            inactivity_reminder=model.inactivity_reminder,
        )

    def to_model(self, user_id: UserId) -> UserNotificationSettings:
        return UserNotificationSettings(
            user_id=user_id,
            weekly_report=self.weekly_report,
            inactivity_reminder=self.inactivity_reminder,
        )
