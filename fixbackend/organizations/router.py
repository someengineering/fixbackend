from typing import List, Annotated
from fastapi import APIRouter, HTTPException
from fixbackend.auth.dependencies import AuthenticatedUser
from sqlalchemy.exc import IntegrityError
from fixbackend.organizations.schemas import Organization, CreateOrganization, OrganizationInvite
from fixbackend.organizations.service import OrganizationServiceDependency
from fixbackend.auth.user_manager import UserManagerDependency
from uuid import UUID
from pydantic import EmailStr

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
    organization_id: UUID,
    user_context: AuthenticatedUser,
    organization_service: OrganizationServiceDependency,
    user_manager: UserManagerDependency,
) -> List[OrganizationInvite]:
    """List all pending invitations for an org."""
    org = await organization_service.get_organization(organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    if user_context.user.email not in [owner.user.email for owner in org.owners]:
        raise HTTPException(status_code=403, detail="You must be an owner of this organization to view the invitations")

    invites = await organization_service.list_invitations(organization_id=organization_id)

    return [OrganizationInvite(
        organization_slug=invite.organization.slug,
        email=invite.user.email,
        expires_at=invite.expires_at,
    ) for invite in invites]


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
        raise HTTPException(status_code=403, detail="You must be an owner of this organization to create an invitation")

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
        raise HTTPException(status_code=403, detail="You must be an owner of this organization to delete an invitation")

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
