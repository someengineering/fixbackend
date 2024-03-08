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

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi_users import exceptions
from fastapi_users.authentication import AuthenticationBackend
from fastapi_users.authentication.strategy.base import Strategy, StrategyDestroyNotSupportedError
from fastapi_users.manager import BaseUserManager

from fixbackend.auth.models import User
from fixbackend.auth.transport import CookieTransport
from fixbackend.config import ConfigDependency
from fixbackend.dependencies import FixDependency
from fixbackend.ids import UserId
from fixbackend import jwt


class FixJWTStrategy(Strategy[User, UserId]):
    def __init__(
        self,
        public_keys: List[rsa.RSAPublicKey],
        private_key: rsa.RSAPrivateKey,
        lifetime_seconds: Optional[int],
        token_audience: List[str] = ["fastapi-users:auth"],
        algorithm: str = "RS256",
    ):
        self.public_keys = public_keys
        self.private_key = private_key
        self.lifetime_seconds = lifetime_seconds
        self.token_audience = token_audience
        self.algorithm = algorithm

    def decode_token(self, token: str) -> Optional[Dict[str, Any]]:
        return jwt.decode_token(token, self.token_audience, self.public_keys)

    async def read_token(self, token: Optional[str], user_manager: BaseUserManager[User, UserId]) -> Optional[User]:
        if token is None:
            return None

        data = jwt.decode_token(token, self.token_audience, self.public_keys)
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
        payload: Dict[str, Any] = {
            "sub": str(user.id),
            "permissions": {str(role.workspace_id): role.permissions().value for role in user.roles},
        }
        if self.lifetime_seconds:
            expire = datetime.utcnow() + timedelta(seconds=self.lifetime_seconds)
            payload["exp"] = expire
        return jwt.encode_token(payload, self.token_audience, self.private_key)

    async def destroy_token(self, token: str, user: User) -> None:
        raise StrategyDestroyNotSupportedError("A JWT can't be invalidated: it's valid until it expires.")


async def get_session_strategy(config: ConfigDependency, fix: FixDependency) -> Strategy[User, UserId]:
    cert_key_pairs = await fix.certificate_store.get_signing_cert_key_pair()
    return FixJWTStrategy(
        public_keys=[ckp.private_key.public_key() for ckp in cert_key_pairs],
        private_key=cert_key_pairs[0].private_key,
        lifetime_seconds=config.session_ttl,
    )


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
