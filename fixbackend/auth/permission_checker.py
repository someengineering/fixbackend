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


from fastapi import HTTPException
from fixbackend.auth.depedencies import AuthenticatedUser
from fixbackend.auth.models import Permission

from logging import getLogger

log = getLogger(__name__)


class PermissionChecker:
    def __init__(self, *required_permissions: Permission):
        self.required_permissions = required_permissions

    async def __call__(
        self,
        user: AuthenticatedUser,
    ) -> bool:
        # role_names: List[str] = []  # if we get the authenticated user, the jwt cookie should be there.
        # if session_token and (token := strategy.decode_token(session_token)):
        #     role_names = token.get("roles", [])

        # user_roles: List[Role] = []
        # for role_name in role_names:
        #     if role := roles_dict.get(role_name):
        #         user_roles.append(role)
        #     else:
        #         log.warning(f"Role {role} is not known to the system. Ignoring.")

        for permission in self.required_permissions:
            for role in user.roles:
                if permission in role.permissions:
                    break
            else:
                raise HTTPException(status_code=403, detail=f"Missing permission {permission.name}")
        return True
