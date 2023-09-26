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
from uuid import UUID

from attrs import frozen
from fastapi_users.models import OAuthAccountProtocol, UserOAuthProtocol

from fixbackend.auth.models import orm


@frozen
class OauthAccount(OAuthAccountProtocol[UUID]):
    id: UUID
    oauth_name: str
    access_token: str
    expires_at: Optional[int]
    refresh_token: Optional[str]
    account_id: str
    account_email: str

    @staticmethod
    def from_orm(acc: orm.OAuthAccount) -> "OauthAccount":
        return OauthAccount(
            id=acc.id,
            oauth_name=acc.oauth_name,
            access_token=acc.access_token,
            expires_at=acc.expires_at,
            refresh_token=acc.refresh_token,
            account_id=acc.account_id,
            account_email=acc.account_email,
        )

    def to_orm(self) -> orm.OAuthAccount:
        return orm.OAuthAccount(
            id=self.id,
            oauth_name=self.oauth_name,
            access_token=self.access_token,
            expires_at=self.expires_at,
            refresh_token=self.refresh_token,
            account_id=self.account_id,
            account_email=self.account_email,
        )


@frozen
class User(UserOAuthProtocol[UUID, OauthAccount]):
    id: UUID
    email: str
    hashed_password: str
    is_active: bool
    is_superuser: bool
    is_verified: bool
    oauth_accounts: List[OauthAccount]

    @staticmethod
    def from_orm(user: orm.User) -> "User":
        return User(
            id=user.id,
            email=user.email,
            hashed_password=user.hashed_password,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            is_verified=user.is_verified,
            oauth_accounts=[OauthAccount.from_orm(acc) for acc in user.oauth_accounts],
        )

    def to_orm(self) -> orm.User:
        return orm.User(
            id=self.id,
            email=self.email,
            hashed_password=self.hashed_password,
            is_active=self.is_active,
            is_superuser=self.is_superuser,
            is_verified=self.is_verified,
            oauth_accounts=[acc.to_orm() for acc in self.oauth_accounts],
        )
