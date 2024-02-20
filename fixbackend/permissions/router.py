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


from typing import Annotated, List
from fastapi import APIRouter, Depends
from fixbackend.permissions.models import RoleName, UserRole, WorkspacePermission
from fixbackend.permissions.permission_checker import WorkspacePermissionChecker
from fixbackend.permissions.role_repository import RoleRepositoryDependency
from fixbackend.permissions.schemas import UserRolesRead, UserRolesUpdate
from fixbackend.workspaces.dependencies import UserWorkspaceDependency


def roles_router() -> APIRouter:
    router = APIRouter()

    @router.get("/{workspace_id}/roles")
    async def list_roles(
        workspace: UserWorkspaceDependency,
        role_repository: RoleRepositoryDependency,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermission.read_roles))],
    ) -> List[UserRolesRead]:
        roles = await role_repository.list_roles_by_workspace_id(workspace.id)
        workspace_users = workspace.all_users()

        users_with_roles = [role.user_id for role in roles]
        users_witout_roles = list(set(workspace_users) - set(users_with_roles))

        no_assigned_roles = [
            UserRole(user_id=user, workspace_id=workspace.id, role_names=RoleName(0)) for user in users_witout_roles
        ]

        roles = no_assigned_roles + roles

        return [UserRolesRead.from_model(role) for role in roles]

    @router.put("/{workspace_id}/roles/{user_id}")
    async def update_user_role(
        workspace: UserWorkspaceDependency,
        update: UserRolesUpdate,
        repository: RoleRepositoryDependency,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermission.update_roles))],
    ) -> UserRolesRead:
        update_model = update.to_model(workspace.id)
        role = await repository.add_roles(update_model.user_id, workspace.id, update_model.role_names, replace=True)
        return UserRolesRead.from_model(role)

    return router
