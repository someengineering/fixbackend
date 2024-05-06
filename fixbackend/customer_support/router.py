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
import logging
from pathlib import Path
from typing import Any, Callable, Coroutine

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRoute

from fixbackend.auth.depedencies import AuthenticatedUser
from fixbackend.auth.models import User
from fixbackend.customer_support.roles_router import roles_router
from fixbackend.customer_support.user_workspaces_router import user_workspaces_router
from fixbackend.customer_support.login_router import auth_router
from fixbackend.dependencies import FixDependencies
from fastapi.templating import Jinja2Templates
from httpx_oauth.clients.google import GoogleOAuth2

from fastapi import status


log = logging.getLogger(__name__)

TemplatesPath = Path(__file__).parent / "templates"


class RedirectToLoginOn401Route(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            try:
                return await original_route_handler(request)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                    return RedirectResponse(url=request.url_for("login_page"), status_code=status.HTTP_303_SEE_OTHER)
                raise

        return custom_route_handler


def admin_console_router(dependencies: FixDependencies, google_client: GoogleOAuth2) -> APIRouter:

    async def get_customer_support_user(
        user: AuthenticatedUser,
    ) -> User:

        if user.email in dependencies.config.customer_support_users:
            return user

        raise HTTPException(status_code=401)

    root = APIRouter()

    templates = Jinja2Templates(directory=TemplatesPath)

    root.include_router(auth_router(dependencies, templates, google_client), prefix="/auth")

    protected_router = APIRouter(
        dependencies=[Depends(get_customer_support_user)], route_class=RedirectToLoginOn401Route
    )

    @protected_router.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> Response:
        return RedirectResponse(url="/roles", status_code=307)

    protected_router.include_router(user_workspaces_router(dependencies, templates))
    protected_router.include_router(roles_router(dependencies, templates))

    root.include_router(protected_router)

    return root
