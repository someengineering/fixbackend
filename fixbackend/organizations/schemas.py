from typing import List
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr
from uuid import UUID
from fixbackend.organizations.models import Organization as OrganizationModel, OrganizationInvite as OrganizationInviteModel

class Organization(BaseModel):
    id: UUID = Field(description="The organization's unique identifier")
    slug: str = Field(description="The organization's unique slug, used in URLs")
    name: str = Field(description="The organization's name, a human-readable string")
    owners: List[EmailStr] = Field(description="The organization's owners, who can manage the organization")
    members: List[EmailStr] = Field(description="The organization's members, who can view the organizatione")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "00000000-0000-0000-0000-000000000000",
                    "slug": "my-org",
                    "name": "My Organization",
                    "owners": ["owner@example.com"],
                    "members": ["member@example.com"],
                }
            ]
        }
    }

    @staticmethod
    def from_orm(model: OrganizationModel) -> "Organization":
        return Organization(
            id=model.id,
            slug=model.slug,
            name=model.name,
            owners=[o.user.email for o in model.owners],
            members=[m.user.email for m in model.members],
        )
    

class CreateOrganization(BaseModel):
    name: str = Field(description="The organization's name, a human-readable string")
    slug: str = Field(description="The organization's unique slug, used in URLs", pattern="^[a-z0-9-]+$")


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

class OrganizationInvite(BaseModel):
    organization_slug: str = Field(description="The slug of the organization to invite the user to")
    email: EmailStr = Field(description="The email address of the user to invite")
    expires_at: datetime = Field(description="The time at which the invitation expires")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "organization_slug": "my-org",
                    "email": "invitee@example.com",
                    "expires_at": "2021-01-01T00:00:00Z",
                }
            ]
        }
    }
