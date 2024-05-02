#  Copyright (c) 2024. Some Engineering
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

from typing import Any, Dict
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from fixbackend.auth.auth_backend import get_auth_backend
from fixbackend.auth.oauth_router import generate_state_token, get_oauth_router
from fixbackend.dependencies import FixDependencies
from fastapi.templating import Jinja2Templates
from httpx_oauth.oauth2 import BaseOAuth2
from fastapi_users.authentication import AuthenticationBackend
from httpx_oauth.clients.google import GoogleOAuth2


async def get_auth_url(
    request: Request, state: str, client: BaseOAuth2[Any], auth_backend: AuthenticationBackend[Any, Any]
) -> str:
    # as defined in oauth_router.py # noqa
    callback_url_name = f"oauth:{client.name}.{auth_backend.name}.callback"
    # where oauth should call us back
    callback_url = str(request.url_for(callback_url_name))
    # the link to start the authorization with the oauth provider
    auth_url = await client.get_authorization_url(callback_url, state)
    return auth_url


def auth_router(dependencies: FixDependencies, templates: Jinja2Templates, google_client: GoogleOAuth2) -> APIRouter:

    router = APIRouter()

    config = dependencies.config

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

    @router.get("/login", response_class=HTMLResponse, name="login_page")
    async def login(request: Request) -> Response:

        state_data: Dict[str, str] = {}
        state_data["redirect_url"] = "/"
        state = generate_state_token(state_data, config.secret, config.oauth_state_token_ttl)

        auth_url = await get_auth_url(request, state, google_client, auth_backend)
        return templates.TemplateResponse(
            request=request, name="login/index.html", context={"request": request, "auth_url": auth_url}
        )

    return router
