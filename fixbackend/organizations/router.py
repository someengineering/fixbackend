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
from fixbackend.organizations.schemas import WorkspaceRead, WorkspaceCreate, WorkspaceInviteRead, ExternalId
from fixbackend.organizations.repository import WorkspaceRepositoryDependency
from fixbackend.ids import WorkspaceId
from fixbackend.config import ConfigDependency


def organizations_router() -> APIRouter:
    router = APIRouter()

    @router.get("/")
    async def list_workspaces(
        user_context: AuthenticatedUser, organization_service: WorkspaceRepositoryDependency
    ) -> List[WorkspaceRead]:
        """List all organizations."""
        orgs = await organization_service.list_workspaces(user_context.user.id)

        return [WorkspaceRead.from_model(org) for org in orgs]

    @router.get("/{workspace_id}")
    async def get_workspace(
        workspace_id: WorkspaceId,
        user_context: AuthenticatedUser,
        organization_service: WorkspaceRepositoryDependency,
    ) -> WorkspaceRead | None:
        """Get an organization."""
        org = await organization_service.get_workspace(workspace_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        if user_context.user.id not in org.all_users():
            raise HTTPException(status_code=403, detail="You are not an owner of this organization")

        return WorkspaceRead.from_model(org)

    @router.post("/")
    async def create_workspace(
        organization: WorkspaceCreate,
        user_context: AuthenticatedUser,
        organization_service: WorkspaceRepositoryDependency,
    ) -> WorkspaceRead:
        """Create an organization."""
        try:
            org = await organization_service.create_workspace(
                name=organization.name, slug=organization.slug, owner=user_context.user
            )
        except IntegrityError:
            raise HTTPException(status_code=409, detail="Organization with this slug already exists")

        return WorkspaceRead.from_model(org)

    @router.get("/{workspace_id}/invites/")
    async def list_invites(
        workspace_id: WorkspaceId,
        user_context: AuthenticatedUser,
        organization_service: WorkspaceRepositoryDependency,
    ) -> List[WorkspaceInviteRead]:
        """List all pending invitations for an org."""
        org = await organization_service.get_workspace(workspace_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        if user_context.user.id not in org.all_users():
            raise HTTPException(
                status_code=403, detail="You must be an owner of this organization to view the invitations"
            )

        invites = await organization_service.list_invitations(workspace_id=workspace_id)

        return [
            WorkspaceInviteRead(
                organization_slug=org.slug,
                user_id=invite.user_id,
                expires_at=invite.expires_at,
            )
            for invite in invites
        ]

    @router.post("/{workspace_id}/invites/")
    async def invite_to_organization(
        workspace_id: WorkspaceId,
        user_email: EmailStr,
        user_context: AuthenticatedUser,
        organization_service: WorkspaceRepositoryDependency,
        user_manager: UserManagerDependency,
    ) -> WorkspaceInviteRead:
        """Invite a user to an organization."""
        org = await organization_service.get_workspace(workspace_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        user = await user_manager.get_by_email(user_email)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        if user_context.user.email not in org.all_users():
            raise HTTPException(
                status_code=403, detail="You must be an owner of this organization to create an invitation"
            )

        invite = await organization_service.create_invitation(workspace_id=workspace_id, user_id=user.id)

        return WorkspaceInviteRead(
            organization_slug=org.slug,
            user_id=user.id,
            expires_at=invite.expires_at,
        )

    @router.delete("/{workspace_id}/invites/{invite_id}")
    async def delete_invite(
        workspace_id: WorkspaceId,
        invite_id: UUID,
        user_context: AuthenticatedUser,
        organization_service: WorkspaceRepositoryDependency,
    ) -> None:
        """Invite a user to an organization."""
        org = await organization_service.get_workspace(workspace_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        if user_context.user.email not in org.all_users():
            raise HTTPException(
                status_code=403, detail="You must be an owner of this organization to delete an invitation"
            )

        await organization_service.delete_invitation(invite_id)

    @router.get("{workspace_id}/invites/{invite_id}/accept")
    async def accept_invitation(
        workspace_id: WorkspaceId,
        invite_id: UUID,
        user_context: AuthenticatedUser,
        organization_service: WorkspaceRepositoryDependency,
    ) -> None:
        """Accept an invitation to an organization."""
        org = await organization_service.get_workspace(workspace_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        invite = await organization_service.get_invitation(invite_id)
        if invite is None:
            raise HTTPException(status_code=404, detail="Invitation not found")

        if user_context.user.id != invite.user_id:
            raise HTTPException(status_code=403, detail="You can only accept invitations for your own account")

        await organization_service.accept_invitation(invite_id)

        return None

    @router.get("/{workspace_id}/cf_url")
    async def get_cf_url(
        workspace_id: WorkspaceId,
        organization_repository: WorkspaceRepositoryDependency,
        config: ConfigDependency,
        user_context: AuthenticatedUser,
        user_workspace_id: TenantDependency,
    ) -> str:
        org = await organization_repository.get_workspace(workspace_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        return (
            f"https://console.aws.amazon.com/cloudformation/home#/stacks/create/review"
            f"?templateURL={config.cf_template_url}"
            "&stackName=FixAccess"
            f"&param_WorkspaceId={workspace_id}"
            f"&param_ExternalId={org.external_id}"
        )

    @router.get("/{workspace_id}/cf_template")
    async def get_cf_template(
        config: ConfigDependency,
    ) -> str:
        return config.cf_template_url

    @router.get("/{workspace_id}/external_id")
    async def get_externa_id(
        workspace_id: WorkspaceId,
        user_context: AuthenticatedUser,
        organization_service: WorkspaceRepositoryDependency,
    ) -> ExternalId:
        """Get an organization's external id."""
        org = await organization_service.get_workspace(workspace_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        if user_context.user.id not in org.all_users():
            raise HTTPException(
                status_code=403, detail="You must be a member of this organization to get an external ID"
            )

        return ExternalId(external_id=org.external_id)

    return router
