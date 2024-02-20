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


from pydantic import BaseModel, Field

from fixbackend.ids import (
    UserId,
    WorkspaceId,
)
from fixbackend.permissions.models import Roles, UserRole


class UserRolesRead(BaseModel):
    user_id: UserId = Field(description="User ID")
    workspace_id: WorkspaceId = Field(description="Workspace ID")
    member: bool = Field(description="if user has member role")
    admin: bool = Field(description="if user has admin role")
    owner: bool = Field(description="if user has owner role")
    billing_admin: bool = Field(description="if user has billing role")

    @staticmethod
    def from_model(model: UserRole) -> "UserRolesRead":
        return UserRolesRead(
            user_id=model.user_id,
            workspace_id=model.workspace_id,
            member=Roles.workspace_member in model.role_names,
            admin=Roles.workspace_admin in model.role_names,
            owner=Roles.workspace_owner in model.role_names,
            billing_admin=Roles.workspace_billing_admin in model.role_names,
        )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "user_id": "00000000-0000-0000-0000-000000000000",
                    "user_email": "foo@example.com",
                    "member": True,
                    "owner": True,
                    "admin": False,
                    "billing_admin": False,
                }
            ]
        }
    }


class UserRolesUpdate(BaseModel):
    user_id: UserId = Field(description="User ID")
    member: bool = Field(description="if user has member role")
    admin: bool = Field(description="if user has admin role")
    owner: bool = Field(description="if user has owner role")
    billing_admin: bool = Field(description="if user has billing role")

    def to_model(self, workspace_id: WorkspaceId) -> UserRole:
        role_names = Roles(0)
        if self.member:
            role_names |= Roles.workspace_member
        if self.admin:
            role_names |= Roles.workspace_admin
        if self.owner:
            role_names |= Roles.workspace_owner
        if self.billing_admin:
            role_names |= Roles.workspace_billing_admin

        return UserRole(user_id=self.user_id, workspace_id=workspace_id, role_names=role_names)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "user_id": "00000000-0000-0000-0000-000000000000",
                    "user_email": "foo@example.com",
                    "member": True,
                    "owner": True,
                    "admin": False,
                    "billing_admin": False,
                }
            ]
        }
    }
