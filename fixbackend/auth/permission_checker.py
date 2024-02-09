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
from fixbackend.auth.models import WorkspacePermission

from logging import getLogger
from fixbackend.ids import WorkspaceId


log = getLogger(__name__)


class WorkspacePermissionChecker:
    def __init__(self, required_permissions: WorkspacePermission):
        self.required_permissions = required_permissions

    async def __call__(
        self,
        user: AuthenticatedUser,
        workspace_id: Annotated[WorkspaceId, Path()],
    ) -> bool:

        for permission in self.required_permissions:
            for role in user.roles:
                # wrong workspace, look at the other role

                if role.workspace_id != workspace_id:
                    continue
                # permission found, go to the next one
                if permission in role.permissions():
                    break
            else:
                raise HTTPException(status_code=403, detail=f"Missing permission {permission.name}")
        return True
