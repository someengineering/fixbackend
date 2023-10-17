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

import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import (
    ec,
    ed448,
    ed25519,
    rsa,
)
from fastapi_users import exceptions
from fastapi_users.authentication import AuthenticationBackend, JWTStrategy
from fastapi_users.authentication.strategy.base import Strategy, StrategyDestroyNotSupportedError
from fastapi_users.manager import BaseUserManager

from fixbackend.auth.models import User
from fixbackend.auth.transport import CookieTransport
from fixbackend.dependencies import FixDependency
from fixbackend.config import ConfigDependency

# copied from jwt package
AllowedPrivateKeys = rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey | ed25519.Ed25519PrivateKey | ed448.Ed448PrivateKey
AllowedPublicKeys = rsa.RSAPublicKey | ec.EllipticCurvePublicKey | ed25519.Ed25519PublicKey | ed448.Ed448PublicKey


class FixJWTStrategy(Strategy[User, UUID]):
    def __init__(
        self,
        public_keys: List[AllowedPublicKeys],
        private_key: AllowedPrivateKeys,
        lifetime_seconds: Optional[int],
        token_audience: List[str] = ["fastapi-users:auth"],
        algorithm: str = "RS256",
    ):
        self.public_keys = public_keys
        self.private_key = private_key
        self.lifetime_seconds = lifetime_seconds
        self.token_audience = token_audience
        self.algorithm = algorithm

    def kid(self, key: AllowedPublicKeys) -> str:
        return hashlib.sha256(
            key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.PKCS1)
        ).hexdigest()[0:8]

    async def read_token(self, token: Optional[str], user_manager: BaseUserManager[User, UUID]) -> Optional[User]:
        if token is None:
            return None

        unverified = jwt.api_jwt.decode_complete(token, options={"verify_signature": False})
        header = unverified["header"]
        key_id = header.get("kid")

        public_key = None

        # poor man JWKS
        available_keys = {self.kid(key): key for key in self.public_keys}

        if not (key_id in available_keys):
            raise ValueError("Token signed with unknown key")

        public_key = available_keys[key_id]

        try:
            data = jwt.decode(jwt=token, key=public_key, algorithms=[self.algorithm], audience=self.token_audience)
            user_id = data.get("sub")
            if user_id is None:
                return None
        except jwt.PyJWTError:
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
            "aud": self.token_audience,
        }
        headers = {
            "kid": self.kid(self.private_key.public_key()),
        }
        if self.lifetime_seconds:
            expire = datetime.utcnow() + timedelta(seconds=self.lifetime_seconds)
            payload["exp"] = expire
        return jwt.encode(payload, self.private_key, algorithm=self.algorithm, headers=headers)

    async def destroy_token(self, token: str, user: User) -> None:
        raise StrategyDestroyNotSupportedError("A JWT can't be invalidated: it's valid until it expires.")


async def get_jwt_strategy(config: ConfigDependency, fix: FixDependency) -> Strategy[User, UUID]:
    if config.env == "local":
        return JWTStrategy(secret=config.secret, lifetime_seconds=None)
    else:
        cert_key_pairs = await fix.certificate_store.get_signing_cert_key_pair()
        return FixJWTStrategy(
            public_keys=[ckp.private_key.public_key() for ckp in cert_key_pairs],
            private_key=cert_key_pairs[0].private_key,
            lifetime_seconds=config.session_ttl,
        )


def get_auth_backend(config: ConfigDependency) -> AuthenticationBackend[Any, Any]:
    cookie_transport = CookieTransport(
        cookie_name="fix.auth",
        cookie_secure=True,
        cookie_httponly=True,
        cookie_samesite="lax",
        cookie_max_age=config.session_ttl,
    )
    return AuthenticationBackend(
        name="jwt",
        transport=cookie_transport,
        get_strategy=get_jwt_strategy,
    )
