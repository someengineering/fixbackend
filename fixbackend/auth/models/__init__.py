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


from typing import Dict, List, Optional
from uuid import UUID

from attrs import frozen
from fastapi_users.models import OAuthAccountProtocol, UserOAuthProtocol

from fixbackend.ids import UserRoleId, UserId, WorkspaceId
from enum import IntFlag
from functools import reduce


# do not change the int
class WorkspacePermission(IntFlag):
    create = 2**0
    read = 2**1
    update = 2**2
    delete = 2**3
    invite_to = 2**4
    remove_from = 2**5
    read_settings = 2**6
    update_settings = 2**7
    update_cloud_accounts = 2**8


class RoleName(IntFlag):
    workspace_member = 2**0
    workspace_admin = 2**1
    workspace_owner = 2**2


workspace_member_permissions = WorkspacePermission.read | WorkspacePermission.create
workspace_admin_permissions = (
    workspace_member_permissions
    | WorkspacePermission.invite_to
    | WorkspacePermission.remove_from
    | WorkspacePermission.update
    | WorkspacePermission.read_settings
    | WorkspacePermission.update_settings
    | WorkspacePermission.update_cloud_accounts
)
workspace_owner_permissions = workspace_admin_permissions | WorkspacePermission.delete

roles_to_permissions: Dict[RoleName, WorkspacePermission] = {
    RoleName.workspace_member: workspace_member_permissions,
    RoleName.workspace_admin: workspace_admin_permissions,
    RoleName.workspace_owner: workspace_owner_permissions,
}


@frozen
class UserRoles:
    id: UserRoleId
    user_id: UserId
    workspace_id: WorkspaceId
    role_names: RoleName

    def permissions(self) -> WorkspacePermission:
        return reduce(
            lambda x, y: x | y,
            [roles_to_permissions[role] for role in self.role_names],
            WorkspacePermission(0),
        )


@frozen
class OAuthAccount(OAuthAccountProtocol[UUID]):
    id: UUID
    oauth_name: str
    access_token: str
    expires_at: Optional[int]
    refresh_token: Optional[str]
    account_id: str
    account_email: str
    username: Optional[str]


@frozen
class User(UserOAuthProtocol[UserId, OAuthAccount]):
    id: UserId
    email: str
    hashed_password: str
    is_active: bool
    is_superuser: bool
    is_verified: bool
    oauth_accounts: List[OAuthAccount]
    roles: List[UserRoles]
