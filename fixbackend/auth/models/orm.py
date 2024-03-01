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


from typing import List, Optional

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID, SQLAlchemyBaseOAuthAccountTableUUID
from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fixbackend.auth import models
from fixbackend.base_model import Base
from fixbackend.ids import UserId


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):

    username: Mapped[Optional[str]] = mapped_column(String(length=320), nullable=True)

    def to_model(self) -> models.OAuthAccount:
        return models.OAuthAccount(
            id=self.id,
            oauth_name=self.oauth_name,
            access_token=self.access_token,
            expires_at=self.expires_at,
            refresh_token=self.refresh_token,
            account_id=self.account_id,
            account_email=self.account_email,
            username=self.username,
        )

    @staticmethod
    def from_model(acc: models.OAuthAccount) -> "OAuthAccount":
        return OAuthAccount(
            id=acc.id,
            oauth_name=acc.oauth_name,
            access_token=acc.access_token,
            expires_at=acc.expires_at,
            refresh_token=acc.refresh_token,
            account_id=acc.account_id,
            account_email=acc.account_email,
        )


class User(SQLAlchemyBaseUserTableUUID, Base):
    otp_secret: Mapped[str] = mapped_column(String(length=64), nullable=True)
    mfa_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)
    oauth_accounts: Mapped[List[OAuthAccount]] = relationship("OAuthAccount", lazy="joined")

    def to_model(self) -> models.User:
        return models.User(
            id=UserId(self.id),
            email=self.email,
            hashed_password=self.hashed_password,
            is_active=self.is_active,
            is_superuser=self.is_superuser,
            is_verified=self.is_verified,
            oauth_accounts=[acc.to_model() for acc in self.oauth_accounts],
            otp_secret=self.otp_secret,
            mfa_active=self.mfa_active,
            roles=[],
        )

    @staticmethod
    def from_model(user: models.User) -> "User":
        return User(
            id=user.id,
            email=user.email,
            hashed_password=user.hashed_password,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            is_verified=user.is_verified,
            otp_secret=user.otp_secret,
            mfa_active=user.mfa_active,
            oauth_accounts=[OAuthAccount.from_model(acc) for acc in user.oauth_accounts],
        )
