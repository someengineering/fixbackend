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

from typing import Annotated, Any, Dict, Sequence
import uuid
from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fixbackend.auth.models import User
from fixbackend.auth.schemas import UserUpdate
from fixbackend.auth.user_manager import UserManager
from fixbackend.auth.user_repository import UserRepository
from fixbackend.dependencies import FixDependencies, ServiceNames
from fastapi.templating import Jinja2Templates
from fixbackend.permissions.role_repository import RoleRepositoryImpl
from fixbackend.workspaces.models import Workspace

from fixbackend.ids import UserId, WorkspaceId
from fixbackend.permissions.models import Roles
from attrs import frozen

from fixbackend.workspaces.repository import WorkspaceRepositoryImpl


@frozen
class WorkspaceTableRow:
    workspace: Workspace
    roles: Dict[str, bool]

    @staticmethod
    def from_user_role(workspace: Workspace, user_role: Roles) -> "WorkspaceTableRow":
        roles = {role: False for role in Roles}
        for role in Roles:
            if role & user_role:  # check if the role is in the user_role
                roles[role] = True
        html_roles = {role.name: value for role, value in roles.items() if role.name}
        return WorkspaceTableRow(workspace=workspace, roles=html_roles)


def users_router(dependencies: FixDependencies, templates: Jinja2Templates) -> APIRouter:

    router = APIRouter()

    user_repo = dependencies.service(ServiceNames.user_repo, UserRepository)
    workspace_repo = dependencies.service(ServiceNames.workspace_repo, WorkspaceRepositoryImpl)
    user_manager = dependencies.service(ServiceNames.user_manager, UserManager)
    role_repo = dependencies.service(ServiceNames.role_repository, RoleRepositoryImpl)

    @router.get("", response_class=HTMLResponse, name="users:index")
    async def index(request: Request) -> Response:
        query = request.query_params.get("query")
        users: Sequence[User] = []
        if query:
            users = await user_repo.search(query)
        else:
            users = await user_repo.list(25, 0)

        context: Dict[str, Any] = {"request": request, "users": users}

        return templates.TemplateResponse(request=request, name="users/index.html", context=context)

    @router.get("/{user_id}", response_class=HTMLResponse, name="users:get_user")
    async def get_user(request: Request, user_id: UserId) -> Response:
        user = await user_repo.get(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        workspaces = await workspace_repo.list_workspaces(user, False)

        roles_dict = {role.workspace_id: role.role_names for role in user.roles}

        workspace_rows = [
            WorkspaceTableRow.from_user_role(workspace, roles_dict.get(workspace.id, Roles(0)))
            for workspace in workspaces
        ]

        context: Dict[str, Any] = {"request": request, "user": user, "workspace_rows": workspace_rows}

        if request.headers.get("HX-Request"):
            context["partial"] = True

        headers = {"Vary": "HX-Request"}

        return templates.TemplateResponse(request=request, name="users/user.html", headers=headers, context=context)

    @router.get("/{user_id}/", response_class=HTMLResponse, name="users:delete_user")
    async def delete_user(request: Request, user_id: UserId) -> Response:
        user = await user_repo.get(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user = await user_manager.update(UserUpdate(is_active=False), user, safe=True)

        context: Dict[str, Any] = {"request": request, "user": user}

        if request.headers.get("HX-Request"):
            context["partial"] = True

        headers = {"Vary": "HX-Request"}

        return templates.TemplateResponse(request=request, name="users/user.html", headers=headers, context=context)

    @router.get("/{user_id}/workspaces_table", response_class=HTMLResponse, name="users:workspaces_table")
    async def workspaces_table(request: Request, user_id: UserId) -> Response:
        user = await user_repo.get(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        workspaces = await workspace_repo.list_workspaces(user)

        roles_dict = {role.workspace_id: role.role_names for role in user.roles}

        workspace_rows = [
            WorkspaceTableRow.from_user_role(workspace, roles_dict.get(workspace.id, Roles(0)))
            for workspace in workspaces
        ]

        context: Dict[str, Any] = {
            "request": request,
            "user": user,
            "workspace_rows": workspace_rows,
        }
        return templates.TemplateResponse(request=request, name="users/workspaces_table.html", context=context)

    @router.get("/{user_id}/workspace_modal", response_class=HTMLResponse, name="users:add_to_workspace_modal")
    async def add_to_workspace_modal(request: Request, user_id: UserId) -> Response:
        user = await user_repo.get(user_id)
        if not user:
            raise HTTPException(status_code=404)

        roles = [role.name for role in Roles]

        return templates.TemplateResponse(
            request=request,
            name="users/add_to_workspace_modal.html",
            context={"request": request, "user": user, "roles": roles},
        )

    @router.post("/{user_id}/workspace_modal", response_class=HTMLResponse, name="users:add_to_workspace")
    async def add_to_workspace(request: Request, user_id: UserId, workspace_id: Annotated[str, Form()]) -> Response:

        workspace_uuid = WorkspaceId(uuid.UUID(workspace_id.strip()))

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

        headers = {"HX-Trigger": "tableRefresh", "Vary": "HX-Trigger"}

        return templates.TemplateResponse(
            request=request,
            name="users/add_to_workspace_success.html",
            headers=headers,
            context={"request": request, "user": user, "workspace_id": workspace_uuid},
        )

    @router.get(
        "/{user_id}/workspace_roles/{workspace_id}", response_class=HTMLResponse, name="users:workspace_roles_modal"
    )
    async def workspace_roles(request: Request, user_id: UserId, workspace_id: WorkspaceId) -> Response:
        user = await user_repo.get(user_id)
        if not user:
            raise HTTPException(status_code=404)

        workspace = await workspace_repo.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(status_code=404)

        roles = next(iter([role.role_names for role in user.roles if role.workspace_id == workspace_id]), Roles(0))

        role = WorkspaceTableRow.from_user_role(workspace, roles)

        return templates.TemplateResponse(
            request=request,
            name="users/user_roles_modal.html",
            context={"request": request, "user": user, "workspace": workspace, "role": role},
        )

    @router.post("/{user_id}/workspace_roles/{workspace_id}", response_class=HTMLResponse, name="users:update_roles")
    async def update_roles(request: Request, user_id: UserId, workspace_id: WorkspaceId) -> Response:
        user = await user_repo.get(user_id)
        if not user:
            raise HTTPException(status_code=404)

        workspace = await workspace_repo.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(status_code=404)
        new_roles = Roles(0)

        form_data = await request.form()
        for key in form_data.keys():
            try:
                role = Roles[key]
                new_roles |= role
            except KeyError:
                continue

        updated_user_role = await role_repo.add_roles(user_id, workspace_id, new_roles, replace_existing=True)

        role_row = WorkspaceTableRow.from_user_role(workspace, updated_user_role.role_names)

        headers = {"HX-Trigger": "tableRefresh", "Vary": "HX-Trigger"}

        return templates.TemplateResponse(
            request=request,
            name="users/user_roles_modal.html",
            headers=headers,
            context={"request": request, "user": user, "workspace": workspace, "role": role_row},
        )

    @router.post("/{user_id}/send_verify", response_class=HTMLResponse, name="users:resend_verification_email")
    async def resend_verification_email(request: Request, user_id: UserId) -> Response:
        user = await user_repo.get(user_id)
        if not user:
            raise HTTPException(status_code=404)

        await user_manager.request_verify(user, request=None)

        return Response(status_code=201, content="<div>Verification email sent</div>")

    return router
