
from fastapi import Response, status
from fastapi.security import APIKeyCookie

from fastapi_users.authentication.transport.base import Transport
from fastapi_users.openapi import OpenAPIResponseType
from fastapi_users.authentication.transport.cookie import CookieTransport


class CookieRedirectTransport(Transport):

    """
    Modified CookieTrasport that performs redirect in addition to setting a cookie.
    """

    scheme: APIKeyCookie

    def __init__(
        self,
        cookie_transport: CookieTransport,
        redirect_path: str = "/"
    ):
        self.cookie_transport = cookie_transport
        self.redirect_path = redirect_path

    async def get_login_response(self, token: str) -> Response:
        response = await self.cookie_transport.get_login_response(token)
        response.status_code = status.HTTP_303_SEE_OTHER
        response.headers.append("Location", self.redirect_path)
        response.headers.append("Content-type", "text/html")
        return response

    async def get_logout_response(self) -> Response:
        return await self.cookie_transport.get_logout_response()

    @staticmethod
    def get_openapi_login_responses_success() -> OpenAPIResponseType:
        return {status.HTTP_303_SEE_OTHER: {"model": None}}

    @staticmethod
    def get_openapi_logout_responses_success() -> OpenAPIResponseType:
        return CookieTransport.get_openapi_logout_responses_success()
