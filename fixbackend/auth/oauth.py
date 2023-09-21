#  Copyright (c) 2023. Some Engineering
#  Copyright (c) 2019 François Voron
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

from typing import Any, Dict, Optional, Tuple, List
from httpx_oauth.clients.github import GitHubOAuth2
from httpx_oauth.clients.google import GoogleOAuth2

from fixbackend.auth.jwt import get_jwt_strategy
from fixbackend.auth.redirect_to_spa import RedirectToSPA
from fixbackend.config import Config
from fixbackend.auth.user_manager import UserManagerDependency

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status, Response, Query
from httpx_oauth.integrations.fastapi import OAuth2AuthorizeCallback
from httpx_oauth.oauth2 import BaseOAuth2, OAuth2Token
from pydantic import BaseModel

from fastapi_users import models
from fastapi_users.authentication import AuthenticationBackend, Strategy
from fastapi_users.exceptions import UserAlreadyExists
from fastapi_users.jwt import SecretType, decode_jwt, generate_jwt
from fastapi_users.router.common import ErrorCode, ErrorModel
from urllib.parse import quote


def google_client(config: Config) -> GoogleOAuth2:
    return GoogleOAuth2(config.google_oauth_client_id, config.google_oauth_client_secret)


def github_client(config: Config) -> GitHubOAuth2:
    return GitHubOAuth2(config.github_oauth_client_id, config.github_oauth_client_secret)


# should only be used for setting up the token via localstorage to launch the SPA
def oauth_redirect_backend(config: Config) -> AuthenticationBackend[Any, Any]:
    transport = RedirectToSPA(redirect_url="/", ttl_seconds=config.session_ttl)
    return AuthenticationBackend(name="spa-redirect", transport=transport, get_strategy=get_jwt_strategy)


STATE_TOKEN_AUDIENCE = "fastapi-users:oauth-state"


class OAuth2AuthorizeResponse(BaseModel):
    authorization_url: str


def generate_state_token(data: Dict[str, str], secret: SecretType, lifetime_seconds: int = 3600) -> str:
    data["aud"] = STATE_TOKEN_AUDIENCE
    return generate_jwt(data, secret, lifetime_seconds)


# forked version of fastapi_users.router.oauth.get_oauth_router
# to allow for redirect_url to be set via the JWT token
def get_oauth_router(
    oauth_client: BaseOAuth2[Any],
    backend: AuthenticationBackend[Any, Any],
    state_secret: SecretType,
    redirect_url: Optional[str] = None,
    associate_by_email: bool = False,
    is_verified_by_default: bool = False,
) -> APIRouter:
    """Generate a router with the OAuth routes."""
    router = APIRouter()
    callback_route_name = f"oauth:{oauth_client.name}.{backend.name}.callback"

    if redirect_url is not None:
        oauth2_authorize_callback = OAuth2AuthorizeCallback(
            oauth_client,
            redirect_url=redirect_url,
        )
    else:
        oauth2_authorize_callback = OAuth2AuthorizeCallback(
            oauth_client,
            route_name=callback_route_name,
        )

    @router.get(
        "/authorize",
        name=f"oauth:{oauth_client.name}.{backend.name}.authorize",
        response_model=OAuth2AuthorizeResponse,
    )
    async def authorize(request: Request, scopes: List[str] = Query(None)) -> OAuth2AuthorizeResponse:
        if redirect_url is not None:
            authorize_redirect_url = redirect_url
        else:
            authorize_redirect_url = str(request.url_for(callback_route_name))

        state_data: Dict[str, str] = {}
        state = generate_state_token(state_data, state_secret)
        authorization_url = await oauth_client.get_authorization_url(
            authorize_redirect_url,
            state,
            scopes,
        )

        return OAuth2AuthorizeResponse(authorization_url=authorization_url)

    @router.get(
        "/callback",
        name=callback_route_name,
        description="The response varies based on the authentication backend used.",
        responses={
            status.HTTP_400_BAD_REQUEST: {
                "model": ErrorModel,
                "content": {
                    "application/json": {
                        "examples": {
                            "INVALID_STATE_TOKEN": {
                                "summary": "Invalid state token.",
                                "value": None,
                            },
                            ErrorCode.LOGIN_BAD_CREDENTIALS: {
                                "summary": "User is inactive.",
                                "value": {"detail": ErrorCode.LOGIN_BAD_CREDENTIALS},
                            },
                        }
                    }
                },
            },
        },
    )
    async def callback(
        request: Request,
        user_manager: UserManagerDependency,
        access_token_state: Tuple[OAuth2Token, str] = Depends(oauth2_authorize_callback),
        strategy: Strategy[models.UP, models.ID] = Depends(backend.get_strategy),
    ) -> Response:
        token, state = access_token_state
        account_id, account_email = await oauth_client.get_id_email(token["access_token"])

        if account_email is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorCode.OAUTH_NOT_AVAILABLE_EMAIL,
            )

        try:
            decoded_state = decode_jwt(state, state_secret, [STATE_TOKEN_AUDIENCE])
        except jwt.DecodeError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)

        try:
            user = await user_manager.oauth_callback(
                oauth_client.name,
                token["access_token"],
                account_id,
                account_email,
                token.get("expires_at"),
                token.get("refresh_token"),
                request,
                associate_by_email=associate_by_email,
                is_verified_by_default=is_verified_by_default,
            )
        except UserAlreadyExists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorCode.OAUTH_USER_ALREADY_EXISTS,
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorCode.LOGIN_BAD_CREDENTIALS,
            )

        # Authenticate
        response = await backend.login(strategy, user)
        # replace the redirect url with the one from the JWT token
        response.headers["location"] = quote(str(decoded_state.get("redirect_url", "/")), safe=":/%#?=@[]!$&'()*+,;")
        await user_manager.on_after_login(user, request, response)
        return response

    return router
