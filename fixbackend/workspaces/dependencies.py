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
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

from typing import Annotated, Union, Literal

from fastapi import Depends, HTTPException, Path

from fixbackend.auth.depedencies import AuthenticatedUser
from fixbackend.ids import WorkspaceId
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepositoryDependency


WorkspaceError = Literal["WorkspaceNotFound", "Unauthorized"]


async def get_optional_user_workspace(
    workspace_id: Annotated[WorkspaceId, Path()],
    user_context: AuthenticatedUser,
    workspace_repository: WorkspaceRepositoryDependency,
) -> Workspace | WorkspaceError:
    workspace = await workspace_repository.get_workspace(workspace_id)
    if workspace is None:
        return "WorkspaceNotFound"

    if user_context.user.id not in workspace.all_users():
        return "Unauthorized"

    return workspace


async def get_user_workspace(
    maybe_workspace: Annotated[Union[Workspace, WorkspaceError], Depends(get_optional_user_workspace)],
) -> Workspace:
    match maybe_workspace:
        case "WorkspaceNotFound":
            raise HTTPException(status_code=404, detail="Workspace not found")
        case "Unauthorized":
            raise HTTPException(status_code=403, detail="You're not a member of this workspace")
        case workspace:
            return workspace


UserWorkspaceDependency = Annotated[Workspace, Depends(get_user_workspace)]
