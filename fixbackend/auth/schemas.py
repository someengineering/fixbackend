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
from typing import Optional

from fastapi import Form
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users import schemas
from pydantic import BaseModel, Field

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


class OAuth2PasswordMFARequestForm(OAuth2PasswordRequestForm):
    def __init__(
        self,
        *,
        username: str = Form(description="The OAuth2 spec requires the exact field name"),
        password: str = Form(description="The OAuth2 spec requires the exact field name"),
        grant_type: Optional[str] = Form(default="password", pattern="password", description="Needs to be present"),
        scope: str = Form(default="", description="A single string with actually several scopes separated by spaces."),
        client_id: Optional[str] = Form(default=None, description="If available: send using HTTP Basic auth."),
        client_secret: Optional[str] = Form(default=None, description="If available: send using HTTP Basic auth."),
        otp: Optional[str] = Form(default=None, description="One time password"),
        recovery_code: Optional[str] = Form(default=None, description="Recovery code")
    ) -> None:
        super().__init__(
            grant_type=grant_type,
            username=username,
            password=password,
            scope=scope,
            client_id=client_id,
            client_secret=client_secret,
        )
        self.otp = otp
        self.recovery_code = recovery_code


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


class OTPConfig(BaseModel):
    uri: str = Field(description="TOTP provisioning URL")
