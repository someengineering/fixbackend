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

from typing import Any, Dict, List

from fastapi import APIRouter, Request
from fastapi_users.authentication import AuthenticationBackend
from fastapi_users.router.oauth import generate_state_token
from httpx_oauth.clients.github import GitHubOAuth2
from httpx_oauth.clients.google import GoogleOAuth2
from httpx_oauth.oauth2 import BaseOAuth2

from fixbackend.auth.auth_backend import get_auth_backend
from fixbackend.auth.depedencies import AuthenticatedUser, fastapi_users
from fixbackend.auth.oauth_router import get_oauth_associate_router, get_oauth_router
from fixbackend.auth.schemas import OAuthProviderAssociateUrl, OAuthProviderAuthUrl, UserCreate, UserRead, UserUpdate
from fixbackend.config import Config


async def get_auth_url(
    request: Request, state: str, client: BaseOAuth2[Any], auth_backend: AuthenticationBackend[Any, Any]
) -> OAuthProviderAuthUrl:
    # as defined in oauth_router.py # noqa
    callback_url_name = f"oauth:{client.name}.{auth_backend.name}.callback"
    # where oauth should call us back
    callback_url = str(request.url_for(callback_url_name))
    # the link to start the authorization with the oauth provider
    auth_url = await client.get_authorization_url(callback_url, state)
    return OAuthProviderAuthUrl(name=client.name, authUrl=auth_url)


async def get_associate_url(
    request: Request, state: str, client: BaseOAuth2[Any], associated: bool
) -> OAuthProviderAssociateUrl:
    # as defined in oauth_router.py # noqa
    callback_url_name = f"oauth-associate:{client.name}.callback"
    # where oauth should call us back
    callback_url = str(request.url_for(callback_url_name))
    # the link to start the authorization with the oauth provider
    auth_url = await client.get_authorization_url(callback_url, state)
    return OAuthProviderAssociateUrl(name=client.name, authUrl=auth_url, associated=associated)


def auth_router(config: Config, google_client: GoogleOAuth2, github_client: GitHubOAuth2) -> APIRouter:
    router = APIRouter()

    auth_backend = get_auth_backend(config)

    router.include_router(
        get_oauth_router(
            google_client,
            auth_backend,
            config.secret,
            is_verified_by_default=True,
            associate_by_email=True,
            state_token_ttl=config.oauth_state_token_ttl,
        ),
        prefix="/google",
        tags=["auth"],
        # oauth routes are not supposed to be called by the user agent, so we don't need to show them in the docs
        include_in_schema=False,
    )

    router.include_router(
        get_oauth_associate_router(
            oauth_client=google_client,
            authenticator=fastapi_users.authenticator,
            state_secret=config.secret,
            requires_verification=True,
        ),
        prefix="/google/associate",
        tags=["auth"],
        include_in_schema=False,
    )

    router.include_router(
        get_oauth_router(
            github_client,
            auth_backend,
            config.secret,
            is_verified_by_default=True,
            associate_by_email=True,
            state_token_ttl=config.oauth_state_token_ttl,
        ),
        prefix="/github",
        tags=["auth"],
        # oauth routes are not supposed to be called by the user agent, so we don't need to show them in the docs
        include_in_schema=False,
    )

    router.include_router(
        get_oauth_associate_router(
            oauth_client=github_client,
            authenticator=fastapi_users.authenticator,
            state_secret=config.secret,
            requires_verification=True,
        ),
        prefix="/github/associate",
        tags=["auth"],
        include_in_schema=False,
    )

    router.include_router(
        fastapi_users.get_auth_router(auth_backend, requires_verification=True),
        prefix="/jwt",
        tags=["auth"],
    )

    router.include_router(
        fastapi_users.get_register_router(user_schema=UserRead, user_create_schema=UserCreate),
        tags=["auth"],
    )

    router.include_router(
        fastapi_users.get_reset_password_router(),
        tags=["auth"],
    )

    router.include_router(
        fastapi_users.get_verify_router(UserRead),
        tags=["auth"],
    )

    @router.get("/oauth-providers", tags=["auth"])
    async def list_all_oauth_providers(request: Request, redirect_url: str = "/") -> List[OAuthProviderAuthUrl]:
        state_data: Dict[str, str] = {}
        state_data["redirect_url"] = redirect_url
        state = generate_state_token(state_data, config.secret, config.oauth_state_token_ttl)

        clients: List[BaseOAuth2[Any]] = [google_client, github_client]
        return [await get_auth_url(request, state, client, auth_backend) for client in clients]

    @router.get("/oauth-associate", tags=["auth"])
    async def list_oauth_associate_providers(
        request: Request, user: AuthenticatedUser, redirect_url: str = "/"
    ) -> List[OAuthProviderAssociateUrl]:
        state_data: Dict[str, str] = {}
        state_data["redirect_url"] = redirect_url
        state_data["sub"] = str(user.id)
        state = generate_state_token(state_data, config.secret, config.oauth_state_token_ttl)

        clients: List[BaseOAuth2[Any]] = [google_client, github_client]
        associated_clients = [
            (client, client.name in [oa.oauth_name for oa in user.oauth_accounts]) for client in clients
        ]
        providers = [
            await get_associate_url(request, state, client, already_associated)
            for client, already_associated in associated_clients
        ]
        return providers

    return router


def users_router() -> APIRouter:
    router = fastapi_users.get_users_router(UserRead, UserUpdate)

    return router
