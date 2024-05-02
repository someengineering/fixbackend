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
from operator import or_
from typing import Dict
from fixbackend.ids import UserId, WorkspaceId
from enum import IntFlag
from functools import reduce
from attrs import frozen


# do not change the int
class WorkspacePermissions(IntFlag):
    create = 2**0
    read = 2**1
    update = 2**2
    delete = 2**3
    invite_to = 2**4
    remove_from = 2**5
    read_settings = 2**6
    update_settings = 2**7
    update_cloud_accounts = 2**8
    read_billing = 2**9
    update_billing = 2**10
    read_roles = 2**11
    update_roles = 2**12


class Roles(IntFlag):
    workspace_member = 2**0
    workspace_admin = 2**1
    workspace_owner = 2**2
    workspace_billing_admin = 2**3


# todo: remove giving members all permissions after FE supports permissions feature.
all_read_permissions = WorkspacePermissions.read | WorkspacePermissions.read_settings | WorkspacePermissions.read_roles
workspace_member_permissions = WorkspacePermissions.read | WorkspacePermissions.create | all_read_permissions

workspace_billing_admin_permissions = WorkspacePermissions.read_billing | WorkspacePermissions.update_billing
workspace_admin_permissions = (
    workspace_member_permissions
    | workspace_billing_admin_permissions
    | WorkspacePermissions.invite_to
    | WorkspacePermissions.remove_from
    | WorkspacePermissions.update
    | WorkspacePermissions.read_settings
    | WorkspacePermissions.update_settings
    | WorkspacePermissions.update_cloud_accounts
    | WorkspacePermissions.read_roles
    | WorkspacePermissions.update_roles
)
workspace_owner_permissions = workspace_admin_permissions | WorkspacePermissions.delete

roles_to_permissions: Dict[Roles, WorkspacePermissions] = {
    Roles.workspace_member: workspace_member_permissions,
    Roles.workspace_admin: workspace_admin_permissions,
    Roles.workspace_owner: workspace_owner_permissions,
    Roles.workspace_billing_admin: workspace_billing_admin_permissions,
}
all_permissions = reduce(or_, [perm.value for perm in WorkspacePermissions])


@frozen
class UserRole:
    user_id: UserId
    workspace_id: WorkspaceId
    role_names: Roles

    def permissions(self) -> WorkspacePermissions:
        return reduce(
            lambda x, y: x | y,
            [roles_to_permissions[role] for role in self.role_names],
            WorkspacePermissions(0),
        )
