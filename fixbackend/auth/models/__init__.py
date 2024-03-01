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

from fixbackend.ids import UserId
from fixbackend.permissions.models import UserRole


@frozen
class OAuthAccount(OAuthAccountProtocol[UUID]):
    id: UUID
    oauth_name: str
    access_token: str
    expires_at: Optional[int]
    refresh_token: Optional[str]
    account_id: str
    account_email: str
    username: Optional[str]


@frozen
class User(UserOAuthProtocol[UserId, OAuthAccount]):
    id: UserId
    email: str
    hashed_password: str
    is_active: bool
    is_superuser: bool
    is_verified: bool
    mfa_active: bool
    otp_secret: Optional[str]
    oauth_accounts: List[OAuthAccount]
    roles: List[UserRole]
