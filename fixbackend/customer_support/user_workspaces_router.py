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

from typing import Annotated, Any, Dict, Optional, Sequence
import uuid
from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fixbackend.auth.user_manager import UserManager
from fixbackend.auth.user_repository import UserRepository
from fixbackend.dependencies import FixDependencies, ServiceNames
from fastapi.templating import Jinja2Templates

from fixbackend.ids import UserId, WorkspaceId
from fixbackend.permissions.models import Roles

from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepositoryImpl


def user_workspaces_router(dependencies: FixDependencies, templates: Jinja2Templates) -> APIRouter:

    router = APIRouter()

    user_repo = dependencies.service(ServiceNames.user_repo, UserRepository)
    user_manager = dependencies.service(ServiceNames.user_manager, UserManager)
    workspace_repo = dependencies.service(ServiceNames.workspace_repo, WorkspaceRepositoryImpl)

    @router.get("/user_workspaces", response_class=HTMLResponse, name="user_workspaces")
    async def workspaces(request: Request) -> Response:

        user_id_query = request.query_params.get("user_id")
        user = None
        workspaces: Sequence[Workspace] = []
        user_id: Optional[UserId] = None
        if user_id_query:
            try:
                user_id = UserId(uuid.UUID(user_id_query))
                user = await user_repo.get(user_id)
            except ValueError:
                pass

        if user:
            workspaces = await workspace_repo.list_workspaces(user)
            user_id = user.id

        context: Dict[str, Any] = {
            "request": request,
            "user": user,
            "workspaces": workspaces,
            "user_id": user_id,
        }
        if request.headers.get("HX-Request"):
            context["partial"] = True

        return templates.TemplateResponse(request=request, name="user_workspaces/index.html", context=context)

    @router.get("/user_workspaces/table", response_class=HTMLResponse, name="user_workspaces_table")
    async def workspaces_table(request: Request) -> Response:
        user_id_query = request.query_params.get("query")
        user = None
        workspaces: Sequence[Workspace] = []
        user_id: Optional[UserId] = None
        if user_id_query:
            try:
                user_id = UserId(uuid.UUID(user_id_query))
                user = await user_repo.get(user_id)
                print("user", user)
            except ValueError:
                pass

        if user:
            workspaces = await workspace_repo.list_workspaces(user)
            user_id = user.id

        context: Dict[str, Any] = {
            "request": request,
            "user": user,
            "workspaces": workspaces,
        }
        print(context)

        return templates.TemplateResponse(request=request, name="user_workspaces/table.html", context=context)

    @router.get("/user_workspaces/search", response_class=HTMLResponse, name="user_workspaces_search")
    async def workspace_user_search(request: Request) -> Response:
        query = request.query_params.get("query")
        if not query:
            raise HTTPException(status_code=404)
        users = await user_repo.search(query)

        return templates.TemplateResponse(
            request=request,
            name="user_workspaces/select.html",
            context={
                "request": request,
                "users": users,
            },
        )

    @router.post(
        "/user_workspaces/user/{user_id}/send_verify", response_class=HTMLResponse, name="resend_verification_email"
    )
    async def resend_verification_email(request: Request, user_id: UserId) -> Response:
        user = await user_repo.get(user_id)
        if not user:
            raise HTTPException(status_code=404)

        await user_manager.request_verify(user, request=None)

        return Response(status_code=201, content="<div>Verification email sent</div>")

    @router.get("/user_workspaces/user/{user_id}/add", response_class=HTMLResponse, name="add_to_workspace_modal")
    async def add_to_workspace_modal(request: Request, user_id: UserId) -> Response:
        user = await user_repo.get(user_id)
        if not user:
            raise HTTPException(status_code=404)

        roles = [role.name for role in Roles]

        return templates.TemplateResponse(
            request=request,
            name="user_workspaces/workspace_modal.html",
            context={"request": request, "user": user, "roles": roles},
        )

    @router.post("/user_workspaces/user/{user_id}/add", response_class=HTMLResponse, name="add_to_workspace_submit")
    async def submit_add_to_workspace(
        request: Request, user_id: UserId, workspace_id: Annotated[str, Form()]
    ) -> Response:

        workspace_uuid = WorkspaceId(uuid.UUID(workspace_id.strip()))

        print(user_id, workspace_uuid)
        user = await user_repo.get(user_id)
        if not user:
            raise HTTPException(status_code=404)

        roles = Roles(0)

        form_data = await request.form()
        for key in form_data.keys():
            try:
                role = Roles[key]
                roles |= role
            except KeyError:
                continue

        await workspace_repo.add_to_workspace(workspace_uuid, user_id, roles)

        headers = {"HX-Trigger": "workspaceAdded"}

        return templates.TemplateResponse(
            request=request,
            name="user_workspaces/add_success.html",
            headers=headers,
            context={"request": request, "user": user, "workspace_id": workspace_uuid},
        )

    return router
