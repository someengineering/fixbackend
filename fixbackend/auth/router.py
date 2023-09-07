from typing import Dict, Any, List
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from fastapi_users.router.oauth import generate_state_token
from httpx_oauth.oauth2 import BaseOAuth2

from fixbackend.auth.dependencies import AuthenticatedUser, fastapi_users
from fixbackend.auth.jwt import jwt_auth_backend, get_jwt_strategy
from fixbackend.auth.oauth import github_client
from fixbackend.auth.oauth import google_client, oauth_redirect_backend
from fixbackend.config import get_config
from fixbackend.auth.schemas import UserRead, UserCreate, OAuthProviderAuthUrl

auth_router = APIRouter()

auth_router.include_router(
    fastapi_users.get_oauth_router(
        google_client, oauth_redirect_backend, get_config().secret, is_verified_by_default=True, associate_by_email=True
    ),
    prefix="/google",
    tags=["auth"],
    # oauth routes are not supposed to be called by the user agent, so we don't need to show them in the docs
    include_in_schema=False,
)

auth_router.include_router(
    fastapi_users.get_oauth_router(
        github_client, oauth_redirect_backend, get_config().secret, is_verified_by_default=True, associate_by_email=True
    ),
    prefix="/github",
    tags=["auth"],
    # oauth routes are not supposed to be called by the user agent, so we don't need to show them in the docs
    include_in_schema=False,
)

auth_router.include_router(
    fastapi_users.get_auth_router(jwt_auth_backend, requires_verification=True),
    prefix="/jwt",
    tags=["auth"],
)

auth_router.include_router(
    fastapi_users.get_register_router(user_schema=UserRead, user_create_schema=UserCreate),
    tags=["auth"],
)

auth_router.include_router(
    fastapi_users.get_reset_password_router(),
    tags=["auth"],
)

auth_router.include_router(
    fastapi_users.get_verify_router(UserRead),
    tags=["auth"],
)


@auth_router.post("/jwt/refresh", tags=["auth"])
async def refresh_jwt(context: AuthenticatedUser) -> Response:
    """Refresh the JWT token if still logged in."""
    return await jwt_auth_backend.login(get_jwt_strategy(), context.user)


async def get_auth_url(request: Request, state: str, client: BaseOAuth2[Any]) -> OAuthProviderAuthUrl:
    # as defined in https://github.com/fastapi-users/fastapi-users/blob/ff9fae631cdae00ebc15f051e54728b3c8d11420/fastapi_users/router/oauth.py#L41 # noqa
    callback_url_name = f"oauth:{client.name}.{oauth_redirect_backend.name}.callback"
    # where oauthshould call us back
    callback_url = str(request.url_for(callback_url_name))
    # the link to start the authorization with google
    auth_url = await client.get_authorization_url(callback_url, state)
    return OAuthProviderAuthUrl(name=client.name, authUrl=auth_url)


@auth_router.get("/oauth-providers", tags=["auth"])
async def list_all_oauth_providers(request: Request) -> List[OAuthProviderAuthUrl]:
    state_data: Dict[str, str] = {}
    state = generate_state_token(state_data, get_config().secret)

    clients: List[BaseOAuth2[Any]] = [google_client, github_client]
    return [await get_auth_url(request, state, client) for client in clients]


login_page_router = APIRouter()


@login_page_router.get("/login", response_class=HTMLResponse)
async def login(request: Request) -> Response:
    state_data: Dict[str, str] = {}
    state = generate_state_token(state_data, get_config().secret)

    google_auth_url = await get_auth_url(request, state, google_client)
    github_auth_url = await get_auth_url(request, state, github_client)
    html_content = f"""
    <html>
        <head>
            <title>FIX Backend</title>
        </head>
        <body>
            <h1>Welcome to FIX Backend!</h1>

            <a href="{google_auth_url.authUrl}">Login via Google</a>
            <br>
            <a href="{github_auth_url.authUrl}">Login via GitHub</a>



        </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)
