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

from datetime import datetime
from enum import StrEnum
from functools import reduce
from typing import List, Literal, Optional, Union
from fixbackend.auth.models import User
from fixbackend.ids import InvitationId, WorkspaceId, UserId, ExternalId

from pydantic import BaseModel, EmailStr, Field

from fixbackend.permissions.models import Roles, UserRole
from fixbackend.workspaces.models import Workspace, WorkspaceInvitation


class WorkspaceRead(BaseModel):
    id: WorkspaceId = Field(description="The workspace's unique identifier")
    slug: str = Field(description="The workspace's unique slug, used in URLs")
    name: str = Field(description="The workspace's name, a human-readable string")
    owners: List[UserId] = Field(description="The workspace's owners, who can manage the organization")
    members: List[UserId] = Field(description="The workspace's members, who can view the organizatione")
    on_hold_since: Optional[datetime] = Field(description="The time at which the workspace was put on hold")
    created_at: datetime = Field(description="The time at which the workspace was created")
    trial_end_days: Optional[int] = Field(description="Days left before the trial ends.")
    user_has_access: bool = Field(description="Whether the user has access to the workspace")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "00000000-0000-0000-0000-000000000000",
                    "slug": "my-org",
                    "name": "My Organization",
                    "owners": ["00000000-0000-0000-0000-000000000000"],
                    "members": ["00000000-0000-0000-0000-000000000000"],
                    "on_hold_since": "2020-01-01T00:00:00Z",
                    "created_at": "2020-01-01T00:00:00Z",
                    "trial_end_days": 13,
                    "user_has_access": True,
                }
            ]
        }
    }

    @classmethod
    def from_model(cls, model: Workspace, user_id: UserId) -> "WorkspaceRead":
        return WorkspaceRead(
            id=model.id,
            slug=model.slug,
            name=model.name,
            owners=[model.owner_id],
            members=model.members,
            on_hold_since=model.payment_on_hold_since,
            created_at=model.created_at,
            trial_end_days=model.trial_end_days(),
            user_has_access=model.paid_tier_access(user_id),
        )


class WorkspaceSettingsRead(BaseModel):
    id: WorkspaceId = Field(description="The workspace's unique identifier")
    slug: str = Field(description="The workspace's unique slug, used in URLs")
    name: str = Field(description="The workspace's name, a human-readable string")
    external_id: ExternalId = Field(description="The workspace's external identifier")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "00000000-0000-0000-0000-000000000000",
                    "slug": "my-org",
                    "name": "My Organization",
                    "external_id": "00000000-0000-0000-0000-000000000000",
                }
            ]
        }
    }

    @classmethod
    def from_model(cls, model: Workspace) -> "WorkspaceSettingsRead":
        return WorkspaceSettingsRead(
            id=model.id,
            slug=model.slug,
            name=model.name,
            external_id=model.external_id,
        )


class WorkspaceSettingsUpdate(BaseModel):
    name: str = Field(description="The workspace's name, a human-readable string")
    generate_new_external_id: bool = Field(description="Whether to generate a new external identifier")


class WorkspaceCreate(BaseModel):
    name: str = Field(description="Workspace name, a human-readable string")
    slug: str = Field(description="Workspace unique slug, used in URLs", pattern="^[a-z0-9-]+$")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "My Organization",
                    "slug": "my-org",
                }
            ]
        }
    }


class WorkspaceInviteRead(BaseModel):
    invite_id: InvitationId = Field(description="The unique identifier of the invitation")
    workspace_id: WorkspaceId = Field(description="The unique identifier of the workspace to invite the user to")
    workspace_name: str = Field(description="The name of the workspace to invite the user to")
    user_email: str = Field(description="The email of the user to invite")
    expires_at: datetime = Field(description="The time at which the invitation expires")
    accepted_at: Optional[datetime] = Field(description="The time at which the invitation was accepted, if any")

    @staticmethod
    def from_model(invite: WorkspaceInvitation, workspace: Workspace) -> "WorkspaceInviteRead":
        return WorkspaceInviteRead(
            invite_id=invite.id,
            workspace_id=invite.workspace_id,
            workspace_name=workspace.name,
            user_email=invite.email,
            expires_at=invite.expires_at,
            accepted_at=invite.accepted_at,
        )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "invite_id": "00000000-0000-0000-0000-000000000000",
                    "workspace_id": "00000000-0000-0000-0000-000000000000",
                    "workspace_name": "My Organization",
                    "user_email": "foo@bar.com",
                    "expires_at": "2020-01-01T00:00:00Z",
                    "accepted_at": "2020-01-01T00:00:00Z",
                }
            ]
        }
    }


class ExternalIdRead(BaseModel):
    external_id: ExternalId = Field(description="The organization's external identifier")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "external_id": "00000000-0000-0000-0000-000000000000",
                }
            ]
        }
    }


class JsonRoleName(StrEnum):
    member = "member"
    admin = "admin"
    owner = "owner"
    billing_admin = "billing_admin"

    def to_role(self) -> Roles:
        match self:
            case JsonRoleName.member:
                return Roles.workspace_member
            case JsonRoleName.admin:
                return Roles.workspace_admin
            case JsonRoleName.owner:
                return Roles.workspace_owner
            case JsonRoleName.billing_admin:
                return Roles.workspace_billing_admin
            case _:
                raise ValueError(f"Unknown role: {self}")


class UserInvite(BaseModel):
    name: str = Field(description="The name of the user")
    email: EmailStr = Field(description="The email of the user")
    roles: List[JsonRoleName] = Field(description="The role of the user")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "Foo Bar",
                    "email": "foo@example.com",
                    "roles": ["admin"],
                }
            ]
        }
    }


class FixUserSource(BaseModel):
    source: Literal["fix"] = "fix"


UserSource = Union[FixUserSource]


class WorkspaceRoleListRead(BaseModel):
    roles: List[str] = Field(description="The roles available in the workspace")

    @staticmethod
    def from_model(role_names: Roles) -> "WorkspaceRoleListRead":

        result = []
        if Roles.workspace_member in role_names:
            result.append(JsonRoleName.member)
        if Roles.workspace_admin in role_names:
            result.append(JsonRoleName.admin)
        if Roles.workspace_owner in role_names:
            result.append(JsonRoleName.owner)
        if Roles.workspace_billing_admin in role_names:
            result.append(JsonRoleName.billing_admin)

        return WorkspaceRoleListRead(roles=[r.value for r in result])

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "roles": ["member", "admin", "owner", "billing_admin"],
                }
            ]
        }
    }


class WorkspaceUserRoleRead(BaseModel):
    member: bool = Field(description="if user has member role")
    admin: bool = Field(description="if user has admin role")
    owner: bool = Field(description="if user has owner role")
    billing_admin: bool = Field(description="if user has billing role")

    @staticmethod
    def from_model(model: List[UserRole]) -> "WorkspaceUserRoleRead":
        role_names = reduce(lambda x, y: x | y, [role.role_names for role in model], Roles(0))

        return WorkspaceUserRoleRead(
            member=Roles.workspace_member in role_names,
            admin=Roles.workspace_admin in role_names,
            owner=Roles.workspace_owner in role_names,
            billing_admin=Roles.workspace_billing_admin in role_names,
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


class WorkspaceUserRead(BaseModel):
    id: UserId = Field(description="The user's unique identifier")
    sources: List[UserSource] = Field(description="Where the user is found")
    name: str = Field(description="The user's name")
    email: str = Field(description="The user's email")
    roles: WorkspaceUserRoleRead = Field(description="The user's roles")
    last_login: Optional[datetime] = Field(description="The user's last login time, if any")

    @staticmethod
    def from_model(user: User, workspace_id: WorkspaceId) -> "WorkspaceUserRead":
        return WorkspaceUserRead(
            id=user.id,
            sources=[FixUserSource()],
            name=user.email,
            email=user.email,
            roles=WorkspaceUserRoleRead.from_model([role for role in user.roles if role.workspace_id == workspace_id]),
            last_login=None,
        )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "sources": ["organization"],
                    "name": "Foo Bar",
                    "email": "foo@example.com",
                    "roles": ["admin"],
                }
            ]
        }
    }
