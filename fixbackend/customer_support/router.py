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
from typing import Annotated, Any, Dict, Optional, Sequence
import uuid

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from fixbackend.auth.user_repository import UserRepository
from fixbackend.dependencies import FixDependencies, ServiceNames
from fixbackend.ids import UserId, WorkspaceId
from fastapi.templating import Jinja2Templates
from attrs import frozen

from fixbackend.permissions.models import Roles, UserRole
from fixbackend.permissions.role_repository import RoleRepositoryImpl
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepositoryImpl


log = logging.getLogger(__name__)


@frozen
class UserRoleRow:
    workspace_id: WorkspaceId
    roles: Dict[str, bool]

    @staticmethod
    def from_user_role(user_role: UserRole) -> "UserRoleRow":
        roles = {role: False for role in Roles}
        for role in Roles:
            if role & user_role.role_names:  # check if the role is in the user_role
                roles[role] = True
        html_roles = {role.name: value for role, value in roles.items() if role.name}
        return UserRoleRow(workspace_id=user_role.workspace_id, roles=html_roles)


def admin_console_router(dependencies: FixDependencies) -> APIRouter:
    router = APIRouter()

    templates = Jinja2Templates(directory="fixbackend/customer_support/templates")

    role_repo = dependencies.service(ServiceNames.role_repository, RoleRepositoryImpl)
    user_repo = dependencies.service(ServiceNames.user_repo, UserRepository)
    workspace_repo = dependencies.service(ServiceNames.workspace_repo, WorkspaceRepositoryImpl)

    @router.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> Response:
        return RedirectResponse(url="/roles", status_code=307)

    @router.get("/roles", response_class=HTMLResponse)
    async def roles(request: Request) -> Response:
        query = request.query_params.get("query")
        user = None
        roles = []
        if query:
            try:
                user_id = UserId(uuid.UUID(query))
                user = await user_repo.get(user_id)
            except ValueError:
                user = await user_repo.get_by_email(query)

        if user:
            roles = [UserRoleRow.from_user_role(role) for role in user.roles]

        context: Dict[str, Any] = {"request": request, "user": user, "roles": roles, "query": query}

        if request.headers.get("HX-Request"):
            context["partial"] = True

        return templates.TemplateResponse(request=request, name="roles/index.html", context=context)

    @router.get("/roles/table", response_class=HTMLResponse)
    async def roles_table(request: Request) -> Response:
        query = request.query_params.get("query")
        if not query:
            raise HTTPException(status_code=404)
        try:
            user_id = UserId(uuid.UUID(query))
            user = await user_repo.get(user_id)
        except ValueError:
            user = await user_repo.get_by_email(query)

        if not user:
            raise HTTPException(status_code=404)

        roles = [UserRoleRow.from_user_role(role) for role in user.roles]

        return templates.TemplateResponse(
            request=request,
            name="roles/roles_table.html",
            context={"request": request, "user": user, "roles": roles},
        )

    @router.get("/roles/user/{user_id}/workspace/{workspace_id}", response_class=HTMLResponse)
    async def user_permissions(request: Request, user_id: UserId, workspace_id: WorkspaceId) -> Response:
        user = await user_repo.get(user_id)
        if not user:
            raise HTTPException(status_code=404)

        roles = [UserRoleRow.from_user_role(role) for role in user.roles if role.workspace_id == workspace_id]

        if not roles:
            raise HTTPException(status_code=404)

        return templates.TemplateResponse(
            request=request,
            name="roles/modal.html",
            context={"request": request, "user": user, "role": roles[0]},
        )

    @router.post("/roles/user/{user_id}/workspace/{workspace_id}", response_class=HTMLResponse)
    async def update_permissions(request: Request, user_id: UserId, workspace_id: WorkspaceId) -> Response:
        user = await user_repo.get(user_id)
        if not user:
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

        headers = {"HX-Trigger": "roleUpdate"}

        return templates.TemplateResponse(
            request=request,
            name="roles/modal.html",
            headers=headers,
            context={"request": request, "user": user, "role": UserRoleRow.from_user_role(updated_user_role)},
        )

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
