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


from typing import Dict, List, Optional, Set
from uuid import UUID

from attrs import frozen
from fastapi_users.models import OAuthAccountProtocol, UserOAuthProtocol

from fixbackend.ids import UserId


@frozen
class Permission:
    name: str


@frozen
class Role:
    name: str
    description: str
    permissions: Set[Permission]


class Permissions:
    invite_to_workspace = Permission(name="workspace:invite_member")
    remove_from_workspace = Permission(name="workspace:remove_member")
    read_workspace = Permission(name="workspace:read")
    update_workspace = Permission(name="workspace:update")
    delete_workspace = Permission(name="workspace:delete")
    create_workspace = Permission(name="workspace:create")


class Roles:
    workspace_member = Role(
        "workspace_member",
        "A member of the workspace",
        {Permissions.read_workspace, Permissions.create_workspace},
    )

    workspace_admin = Role(
        "workspace_admin",
        "An admin of the workspace",
        workspace_member.permissions
        | {
            Permissions.invite_to_workspace,
            Permissions.remove_from_workspace,
            Permissions.update_workspace,
        },
    )

    workspace_owner = Role(
        "workspace_owner", "The owner of the workspace", workspace_admin.permissions | {Permissions.delete_workspace}
    )


all_roles = [Roles.workspace_member, Roles.workspace_admin, Roles.workspace_owner]

roles_dict: Dict[str, Role] = {role.name: role for role in all_roles}


@frozen
class OAuthAccount(OAuthAccountProtocol[UUID]):
    id: UUID
    oauth_name: str
    access_token: str
    expires_at: Optional[int]
    refresh_token: Optional[str]
    account_id: str
    account_email: str


@frozen
class User(UserOAuthProtocol[UserId, OAuthAccount]):
    id: UserId
    email: str
    hashed_password: str
    is_active: bool
    is_superuser: bool
    is_verified: bool
    oauth_accounts: List[OAuthAccount]
    roles: List[Role]
