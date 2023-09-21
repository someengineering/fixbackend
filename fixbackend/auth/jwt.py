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

from typing import Any
from fastapi_users.authentication import JWTStrategy, AuthenticationBackend, CookieTransport
from fixbackend.config import ConfigDependency


def get_jwt_strategy(config: ConfigDependency) -> JWTStrategy[Any, Any]:
    return JWTStrategy(secret=config.secret, lifetime_seconds=config.session_ttl)


def get_cookie_auth_backend(config: ConfigDependency) -> AuthenticationBackend[Any, Any]:
    cookie_transport = CookieTransport(
        cookie_name="fix.auth",
        cookie_secure=True,
        cookie_httponly=True,
        cookie_samesite="strict",
        cookie_max_age=config.session_ttl,
    )
    return AuthenticationBackend(
        name="cookie",
        transport=cookie_transport,
        get_strategy=get_jwt_strategy,
    )
