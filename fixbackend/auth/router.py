from typing import Dict
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from fastapi_users.router.oauth import generate_state_token
from httpx_oauth.oauth2 import BaseOAuth2

from fixbackend.config import get_config
from fixbackend.auth.oauth import google_client, github_client, oauth_redirect_backend
from fixbackend.auth.jwt import jwt_auth_backend, get_jwt_strategy
from fixbackend.auth.dependencies import AuthenticatedUser, fastapi_users
from fixbackend.auth.jwt import jwt_auth_backend, get_jwt_strategy
from fixbackend.auth.oauth import google_client, oauth_redirect_backend
from fixbackend.config import get_config

router = APIRouter()

router.include_router(
    fastapi_users.get_oauth_router(
        google_client, oauth_redirect_backend, get_config().secret, is_verified_by_default=True, associate_by_email=True
    ),
    prefix="/auth/google",
    tags=["auth"],
)

router.include_router(
    fastapi_users.get_oauth_router(github_client, oauth_redirect_backend, get_config().secret, is_verified_by_default=True, associate_by_email=True),
    prefix="/auth/github",
    tags=["auth"],
)


@router.get("/login", response_class=HTMLResponse)
async def login(request: Request) -> Response:
    state_data: Dict[str, str] = {}
    state = generate_state_token(state_data, get_config().secret)
    async def get_auth_url(client: BaseOAuth2) -> str:
        # as defined in https://github.com/fastapi-users/fastapi-users/blob/ff9fae631cdae00ebc15f051e54728b3c8d11420/fastapi_users/router/oauth.py#L41
        callback_url_name = f"oauth:{client.name}.{oauth_redirect_backend.name}.callback"
        # where google should call us back
        callback_url = str(request.url_for(callback_url_name))
        # the link to start the authorization with google
        auth_url = await client.get_authorization_url(callback_url, state)
        return auth_url

    google_auth_url = await get_auth_url(google_client)
    github_auth_url = await get_auth_url(github_client)
    html_content = f"""
    <html>
        <head>
            <title>FIX Backend</title>
        </head>
        <body>
            <h1>Welcome to FIX Backend!</h1>

            <a href="{google_auth_url}">Login via Google</a>
            <br>
            <a href="{github_auth_url}">Login via GitHub</a>

        </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)


@router.post("/auth/jwt/refresh")
async def refresh_jwt(context: AuthenticatedUser) -> Response:
    """Refresh the JWT token if still logged in."""
    return await jwt_auth_backend.login(get_jwt_strategy(), context.user)
