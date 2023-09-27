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

from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import EmailStr
from sqlalchemy.exc import IntegrityError

from fixbackend.auth.current_user_dependencies import AuthenticatedUser, TenantDependency
from fixbackend.auth.dependencies import UserManagerDependency
from fixbackend.organizations.schemas import Organization, CreateOrganization, OrganizationInvite, ExternalId
from fixbackend.organizations.dependencies import OrganizationServiceDependency
from fixbackend.config import ConfigDependency


def organizations_router() -> APIRouter:
    router = APIRouter()

    @router.get("/")
    async def list_organizations(
        user_context: AuthenticatedUser, organization_service: OrganizationServiceDependency
    ) -> List[Organization]:
        """List all organizations."""
        orgs = await organization_service.list_organizations(user_context.user.id, with_users=True)

        return [Organization.from_orm(org) for org in orgs]

    @router.get("/{organization_id}")
    async def get_organization(
        organization_id: UUID, user_context: AuthenticatedUser, organization_service: OrganizationServiceDependency
    ) -> Organization | None:
        """Get an organization."""
        org = await organization_service.get_organization(organization_id, with_users=True)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        if user_context.user.email not in [owner.user.email for owner in org.owners]:
            raise HTTPException(status_code=403, detail="You are not an owner of this organization")

        return Organization.from_orm(org)

    @router.post("/")
    async def create_organization(
        organization: CreateOrganization,
        user_context: AuthenticatedUser,
        organization_service: OrganizationServiceDependency,
    ) -> Organization:
        """Create an organization."""
        try:
            org = await organization_service.create_organization(
                name=organization.name, slug=organization.slug, owner=user_context.user
            )
        except IntegrityError:
            raise HTTPException(status_code=409, detail="Organization with this slug already exists")

        return Organization.from_orm(org)

    @router.get("/{organization_id}/invites/")
    async def list_invites(
        organization_id: UUID, user_context: AuthenticatedUser, organization_service: OrganizationServiceDependency
    ) -> List[OrganizationInvite]:
        """List all pending invitations for an org."""
        org = await organization_service.get_organization(organization_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        if user_context.user.email not in [owner.user.email for owner in org.owners]:
            raise HTTPException(
                status_code=403, detail="You must be an owner of this organization to view the invitations"
            )

        invites = await organization_service.list_invitations(organization_id=organization_id)

        return [
            OrganizationInvite(
                organization_slug=invite.organization.slug,
                email=invite.user.email,
                expires_at=invite.expires_at,
            )
            for invite in invites
        ]

    @router.post("/{organization_id}/invites/")
    async def invite_to_organization(
        organization_id: UUID,
        user_email: EmailStr,
        user_context: AuthenticatedUser,
        organization_service: OrganizationServiceDependency,
        user_manager: UserManagerDependency,
    ) -> OrganizationInvite:
        """Invite a user to an organization."""
        org = await organization_service.get_organization(organization_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        user = await user_manager.get_by_email(user_email)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        if user_context.user.email not in [owner.user.email for owner in org.owners]:
            raise HTTPException(
                status_code=403, detail="You must be an owner of this organization to create an invitation"
            )

        invite = await organization_service.create_invitation(organization_id=organization_id, user_id=user.id)

        return OrganizationInvite(
            organization_slug=org.slug,
            email=user.email,
            expires_at=invite.expires_at,
        )

    @router.delete("/{organization_id}/invites/{invite_id}")
    async def delete_invite(
        organization_id: UUID,
        invite_id: UUID,
        user_context: AuthenticatedUser,
        organization_service: OrganizationServiceDependency,
    ) -> None:
        """Invite a user to an organization."""
        org = await organization_service.get_organization(organization_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        if user_context.user.email not in [owner.user.email for owner in org.owners]:
            raise HTTPException(
                status_code=403, detail="You must be an owner of this organization to delete an invitation"
            )

        await organization_service.delete_invitation(invite_id)

    @router.get("/invites/{invite_id}/accept")
    async def accept_invitation(
        organization_id: UUID,
        invite_id: UUID,
        user_context: AuthenticatedUser,
        organization_service: OrganizationServiceDependency,
    ) -> None:
        """Accept an invitation to an organization."""
        org = await organization_service.get_organization(organization_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        invite = await organization_service.get_invitation(invite_id)
        if invite is None:
            raise HTTPException(status_code=404, detail="Invitation not found")

        if user_context.user.id != invite.user_id:
            raise HTTPException(status_code=403, detail="You can only accept invitations for your own account")

        await organization_service.accept_invitation(invite_id)

        return None

    @router.get("/{organization_id}/cf_url")
    async def get_cf_url(
        organization_id: UUID,
        user_context: AuthenticatedUser,
        tenant_id: TenantDependency,
        organization_service: OrganizationServiceDependency,
        config: ConfigDependency,
    ) -> str:
        org = await organization_service.get_organization(organization_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        return (
            f"https://console.aws.amazon.com/cloudformation/home#/stacks/create/review"
            f"?templateURL={config.cf_template_url}"
            "&stackName=FixAccess"
            f"&param_FixTenantId={tenant_id}"
            f"&param_FixExternalId={org.external_id}"
        )

    @router.get("/{organization_id}/external_id")
    async def get_externa_id(
        organization_id: UUID,
        user_context: AuthenticatedUser,
        organization_service: OrganizationServiceDependency,
    ) -> ExternalId:
        """Get an organization's external id."""
        org = await organization_service.get_organization(organization_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        if user_context.user.email not in [owner.user.email for owner in org.owners + org.members]:
            raise HTTPException(
                status_code=403, detail="You must be a member of this organization to get an external ID"
            )

        return ExternalId(external_id=org.external_id)

    return router
