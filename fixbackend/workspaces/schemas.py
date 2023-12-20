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
from typing import List, Optional
from fixbackend.auth.models import User
from fixbackend.ids import WorkspaceId, UserId, ExternalId

from pydantic import BaseModel, EmailStr, Field

from fixbackend.workspaces.models import Workspace, WorkspaceInvitation


class WorkspaceRead(BaseModel):
    id: WorkspaceId = Field(description="The workspace's unique identifier")
    slug: str = Field(description="The workspace's unique slug, used in URLs")
    name: str = Field(description="The workspace's name, a human-readable string")
    owners: List[UserId] = Field(description="The workspace's owners, who can manage the organization")
    members: List[UserId] = Field(description="The workspace's members, who can view the organizatione")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "00000000-0000-0000-0000-000000000000",
                    "slug": "my-org",
                    "name": "My Organization",
                    "owners": ["00000000-0000-0000-0000-000000000000"],
                    "members": ["00000000-0000-0000-0000-000000000000"],
                }
            ]
        }
    }

    @classmethod
    def from_model(cls, model: Workspace) -> "WorkspaceRead":
        return WorkspaceRead(
            id=model.id,
            slug=model.slug,
            name=model.name,
            owners=model.owners,
            members=model.members,
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
    workspace_id: WorkspaceId = Field(description="The unique identifier of the workspace to invite the user to")
    workspace_name: str = Field(description="The name of the workspace to invite the user to")
    user_email: str = Field(description="The email of the user to invite")
    expires_at: datetime = Field(description="The time at which the invitation expires")
    accepted_at: Optional[datetime] = Field(description="The time at which the invitation was accepted, if any")

    @staticmethod
    def from_model(invite: WorkspaceInvitation, workspace: Workspace) -> "WorkspaceInviteRead":
        return WorkspaceInviteRead(
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
                    "organization_slug": "my-org",
                    "user_email": "foo@bar.com",
                    "expires_at": "2021-01-01T00:00:00Z",
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


class UserInvite(BaseModel):
    name: str = Field(description="The name of the user")
    email: EmailStr = Field(description="The email of the user")
    roles: List[str] = Field(description="The role of the user")

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


class WorkspaceUserRead(BaseModel):
    id: UserId = Field(description="The user's unique identifier")
    sources: List[str] = Field(description="Where the user is found")
    name: str = Field(description="The user's name")
    email: str = Field(description="The user's email")
    roles: List[str] = Field(description="The user's roles")
    last_login: Optional[datetime] = Field(description="The user's last login time, if any")

    @staticmethod
    def from_model(user: User) -> "WorkspaceUserRead":
        return WorkspaceUserRead(
            id=user.id,
            sources=[],
            name=user.email,
            email=user.email,
            roles=[],
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
