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

from typing import Any, Optional, Literal
from fastapi import Response
from fastapi_users.authentication import JWTStrategy, AuthenticationBackend, CookieTransport
from fixbackend.config import ConfigDependency


def get_jwt_strategy(config: ConfigDependency) -> JWTStrategy[Any, Any]:
    return JWTStrategy(secret=config.secret, lifetime_seconds=config.session_ttl)


class FixCookieTransport(CookieTransport):
    def __init__(
        self,
        cookie_name: str,
        cookie_max_age: Optional[int] = None,
        cookie_path: str = "/",
        cookie_domain: Optional[str] = None,
        cookie_secure: bool = True,
        cookie_httponly: bool = True,
        cookie_samesite: Literal["lax", "strict", "none"] = "lax",
    ):
        super().__init__(
            cookie_name=cookie_name,
            cookie_max_age=cookie_max_age,
            cookie_path=cookie_path,
            cookie_domain=cookie_domain,
            cookie_secure=cookie_secure,
            cookie_httponly=cookie_httponly,
            cookie_samesite=cookie_samesite,
        )

    def _set_login_cookie(self, response: Response, token: str) -> Response:
        response.set_cookie("fix.authenticated", value="1", samesite="strict", max_age=self.cookie_max_age)
        return super()._set_login_cookie(response, token)

    def _set_logout_cookie(self, response: Response) -> Response:
        response.set_cookie("fix.authenticated", value="0", samesite="strict", max_age=self.cookie_max_age)
        return super()._set_logout_cookie(response)


def get_auth_backend(config: ConfigDependency) -> AuthenticationBackend[Any, Any]:
    cookie_transport = FixCookieTransport(
        cookie_name="fix.auth",
        cookie_secure=True,
        cookie_httponly=True,
        cookie_samesite="strict",
        cookie_max_age=config.session_ttl,
    )
    return AuthenticationBackend(
        name="jwt",
        transport=cookie_transport,
        get_strategy=get_jwt_strategy,
    )
