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
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID, SQLAlchemyBaseOAuthAccountTableUUID
from sqlalchemy import String, Boolean, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fixbackend.auth import models
from fixbackend.base_model import Base, CreatedUpdatedMixin
from fixbackend.ids import UserId, WorkspaceId

from fixbackend.permissions.role_repository import UserRoleAssignmentEntity
from fixbackend.sqlalechemy_extensions import GUID, UTCDateTime


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


class UserMFARecoveryCode(Base):
    __tablename__ = "user_mfa_recovery_code"
    user_id: Mapped[UserId] = mapped_column(GUID, ForeignKey("user.id"), primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(length=64), primary_key=True)


class User(SQLAlchemyBaseUserTableUUID, CreatedUpdatedMixin, Base):
    otp_secret: Mapped[Optional[str]] = mapped_column(String(length=64), nullable=True)
    is_mfa_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)
    oauth_accounts: Mapped[List[OAuthAccount]] = relationship("OAuthAccount", lazy="joined")
    roles: Mapped[List[UserRoleAssignmentEntity]] = relationship(
        "UserRoleAssignmentEntity", backref="user", lazy="joined"
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    last_active: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    auth_min_time: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)

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
            is_mfa_active=self.is_mfa_active,
            roles=[role.to_model() for role in self.roles],
            created_at=self.created_at,
            auth_min_time=self.auth_min_time,
        )


class ApiToken(CreatedUpdatedMixin, Base):
    id: Mapped[UUID] = mapped_column(GUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(length=128), nullable=False)
    hash: Mapped[str] = mapped_column(String(length=512), nullable=False)
    user_id: Mapped[UserId] = mapped_column(GUID, ForeignKey("user.id"), nullable=False)
    workspace_id: Mapped[Optional[WorkspaceId]] = mapped_column(GUID, ForeignKey("organization.id"), nullable=True)
    permission: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)

    __tablename__ = "api_token"
    __table_args__ = (UniqueConstraint("user_id", "name", name="unique_user_token_name"),)

    def to_model(self) -> models.ApiToken:
        return models.ApiToken(
            id=self.id,
            name=self.name,
            hash=self.hash,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            permission=self.permission,
            created_at=self.created_at,
            updated_at=self.updated_at,
            last_used_at=self.last_used_at,
        )
