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

from fastapi import Response, status
from fastapi.security.base import SecurityBase
from fastapi.responses import RedirectResponse

from fastapi_users.authentication.transport.base import Transport
from fastapi_users.openapi import OpenAPIResponseType
from fastapi_users.authentication.transport.base import TransportLogoutNotSupportedError


class RedirectToSPA(Transport):

    """
    A "pseudo" transport used only in oauth routers to set the local storage and redirect to SPA
    """

    scheme: SecurityBase  # not used

    def __init__(self, redirect_url: str, ttl_seconds: int):
        self.redirect_url = redirect_url
        self.ttl_seconds = ttl_seconds

    async def get_login_response(self, token: str) -> Response:
        response = RedirectResponse(url=self.redirect_url, status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            "fix.auth", value=token, httponly=True, secure=True, samesite="strict", expires=self.ttl_seconds
        )
        response.set_cookie("fix.authenticated", value="1", samesite="strict", expires=self.ttl_seconds)
        return response

    async def get_logout_response(self) -> Response:
        raise TransportLogoutNotSupportedError()

    @staticmethod
    def get_openapi_login_responses_success() -> OpenAPIResponseType:
        return {status.HTTP_303_SEE_OTHER: {"model": None}}

    @staticmethod
    def get_openapi_logout_responses_success() -> OpenAPIResponseType:
        return {status.HTTP_200_OK: {"model": None}}
