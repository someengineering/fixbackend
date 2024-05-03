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

from fixbackend.auth.depedencies import OptionalAuthenticatedUser
from fixbackend.ids import WorkspaceId
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepositoryDependency
from fixbackend.logging_context import set_workspace_id


WorkspaceError = Literal["WorkspaceNotFound", "Unauthorized", "Forbidden", "TrialEnded"]


async def get_optional_user_workspace(
    workspace_id: Annotated[WorkspaceId, Path()],
    user: OptionalAuthenticatedUser,
    workspace_repository: WorkspaceRepositoryDependency,
) -> Workspace | WorkspaceError:
    if user is None:
        return "Unauthorized"

    set_workspace_id(workspace_id)
    workspace = await workspace_repository.get_workspace(workspace_id)
    if workspace is None:
        return "WorkspaceNotFound"

    if user.id not in workspace.all_users():
        return "Forbidden"

    if not workspace.paid_tier_access(user.id):
        return "TrialEnded"

    return workspace


async def get_user_workspace(
    maybe_workspace: Annotated[Union[Workspace, WorkspaceError], Depends(get_optional_user_workspace)],
    user: OptionalAuthenticatedUser,
) -> Workspace:
    match maybe_workspace:
        case "Unauthorized":
            raise HTTPException(status_code=401, detail="unauthorized")
        case "WorkspaceNotFound":
            raise HTTPException(status_code=404, detail="workspace_not_found")
        case "Forbidden":
            raise HTTPException(status_code=403, detail="not_a_workspace_member")
        case "TrialEnded":
            raise HTTPException(status_code=403, detail="trial_ended")
        case workspace if user and not workspace.paid_tier_access(user.id):
            raise HTTPException(status_code=403, detail="workspace_payment_on_hold")
        case workspace:
            return workspace


UserWorkspaceDependency = Annotated[Workspace, Depends(get_user_workspace)]
