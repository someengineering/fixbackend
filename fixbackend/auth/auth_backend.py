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

from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi_users import exceptions
from fastapi_users.authentication import AuthenticationBackend
from fastapi_users.authentication.strategy.base import Strategy, StrategyDestroyNotSupportedError
from fastapi_users.manager import BaseUserManager
from fixcloudutils.util import utc

from fixbackend import fix_jwt
from fixbackend.auth.models import User
from fixbackend.auth.transport import CookieTransport
from fixbackend.certificates.cert_store import CertificateStore
from fixbackend.config import ConfigDependency
from fixbackend.dependencies import FixDependency, ServiceNames
from fixbackend.ids import UserId, WorkspaceId


class FixJWTStrategy(Strategy[User, UserId]):
    def __init__(
        self,
        certstore: CertificateStore,
        lifetime_seconds: Optional[int],
        token_audience: Optional[List[str]] = None,
        algorithm: str = "RS256",
    ):
        self.certstore = certstore
        self.lifetime_seconds = lifetime_seconds
        self.token_audience = token_audience or ["fastapi-users:auth"]
        self.algorithm = algorithm

    async def decode_token(self, token: str) -> Optional[Dict[str, Any]]:
        public_keys = await self.certstore.public_keys()
        return fix_jwt.decode_token(token, self.token_audience, public_keys)

    async def read_token(self, token: Optional[str], user_manager: BaseUserManager[User, UserId]) -> Optional[User]:
        if token is None:
            return None

        public_keys = await self.certstore.public_keys()
        data = fix_jwt.decode_token(token, self.token_audience, public_keys)
        if data is None:
            return None

        user_id = data.get("sub")
        if user_id is None:
            return None

        try:
            parsed_id = user_manager.parse_id(user_id)
            user = await user_manager.get(parsed_id)
            return user
        except (exceptions.UserNotExists, exceptions.InvalidID):
            return None

    async def write_token(self, user: User) -> str:
        permissions = {role.workspace_id: role.permissions().value for role in user.roles}
        return await self.create_token(str(user.id), "login", permissions)

    async def create_token(self, sub: str, token_origin: str, permissions: Dict[WorkspaceId, int]) -> str:
        payload: Dict[str, Any] = {
            "sub": sub,
            "token_origin": token_origin,
            "permissions": {str(ws): perms for ws, perms in permissions.items()},
        }
        if self.lifetime_seconds:
            expire = utc() + timedelta(seconds=self.lifetime_seconds)
            payload["exp"] = expire

        private_key = await self.certstore.private_key()
        return fix_jwt.encode_token(payload, self.token_audience, private_key)

    async def destroy_token(self, token: str, user: User) -> None:
        raise StrategyDestroyNotSupportedError("A JWT can't be invalidated: it's valid until it expires.")


async def get_session_strategy(fix: FixDependency) -> Strategy[User, UserId]:
    return fix.service(ServiceNames.jwt_strategy, FixJWTStrategy)


session_cookie_name = "session_token"


def cookie_transport(session_ttl: int) -> CookieTransport:
    return CookieTransport(
        cookie_name=session_cookie_name,
        cookie_secure=True,
        cookie_httponly=True,
        cookie_samesite="lax",
        cookie_max_age=session_ttl,
    )


def get_auth_backend(config: ConfigDependency) -> AuthenticationBackend[Any, Any]:
    return AuthenticationBackend(
        name="jwt",
        transport=cookie_transport(config.session_ttl),
        get_strategy=get_session_strategy,
    )
