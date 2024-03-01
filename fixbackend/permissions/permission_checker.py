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


from typing import Annotated
from fastapi import HTTPException, Path
from fixbackend.auth.depedencies import AuthenticatedUser
from fixbackend.permissions.models import WorkspacePermissions
from fixbackend.permissions.validator import validate_workspace_permissions

from logging import getLogger
from fixbackend.ids import WorkspaceId


log = getLogger(__name__)


class WorkspacePermissionChecker:
    def __init__(self, required_permissions: WorkspacePermissions):
        self.required_permissions = required_permissions

    async def __call__(
        self,
        user: AuthenticatedUser,
        workspace_id: Annotated[WorkspaceId, Path()],
    ) -> bool:

        error = validate_workspace_permissions(user, workspace_id, self.required_permissions)
        if error:
            raise HTTPException(status_code=403, detail=error)
        return True
