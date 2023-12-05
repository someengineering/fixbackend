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
from typing import List
from uuid import UUID
from fixbackend.ids import WorkspaceId, UserId, ExternalId

from pydantic import BaseModel, Field

from fixbackend.workspaces.models import Workspace


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
    organization_slug: str = Field(description="The slug of the workspace to invite the user to")
    user_id: UserId = Field(description="The id of the user to invite")
    expires_at: datetime = Field(description="The time at which the invitation expires")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "organization_slug": "my-org",
                    "user_id": "00000000-0000-0000-0000-000000000000",
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
