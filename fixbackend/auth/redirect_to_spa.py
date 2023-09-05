from fastapi import Response, status
from fastapi.security.base import SecurityBase

from fastapi_users.authentication.transport.base import Transport
from fastapi_users.openapi import OpenAPIResponseType
from fastapi_users.authentication.transport.base import TransportLogoutNotSupportedError


class RedirectToSPA(Transport):

    """
    A "pseudo" transport used only in oauth routers to set the local storage and redirect to SPA
    """

    scheme: SecurityBase  # not used

    def __init__(self, redirect_path: str = "/app"):
        self.redirect_path = redirect_path

    async def get_login_response(self, token: str) -> Response:
        payload = f"""
    <!DOCTYPE html>
    <html>
        <head>
            <script>
                localStorage.setItem("fix-jwt", "{token}");
                window.location.replace("{self.redirect_path}");
            </script>
        </head>
        <body></body>
    </html>"""

        response = Response(content=payload, status_code=status.HTTP_200_OK, media_type="text/html")
        return response

    async def get_logout_response(self) -> Response:
        raise TransportLogoutNotSupportedError()

    @staticmethod
    def get_openapi_login_responses_success() -> OpenAPIResponseType:
        return {status.HTTP_200_OK: {"model": None}}

    @staticmethod
    def get_openapi_logout_responses_success() -> OpenAPIResponseType:
        return {status.HTTP_200_OK: {"model": None}}
