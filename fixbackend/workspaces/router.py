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

from fastapi import APIRouter, HTTPException, Request
from pydantic import EmailStr
from sqlalchemy.exc import IntegrityError

from fixbackend.auth.depedencies import AuthenticatedUser
from fixbackend.config import ConfigDependency
from fixbackend.ids import InvitationId, WorkspaceId
from fixbackend.workspaces.invitation_repository import InvitationRepositoryDependency
from fixbackend.workspaces.invitation_service import InvitationServiceDependency
from fixbackend.workspaces.repository import WorkspaceRepositoryDependency
from fixbackend.workspaces.dependencies import UserWorkspaceDependency
from fixbackend.workspaces.schemas import (
    ExternalIdRead,
    WorkspaceCreate,
    WorkspaceInviteRead,
    WorkspaceRead,
    WorkspaceSettingsRead,
    WorkspaceSettingsUpdate,
)


def workspaces_router() -> APIRouter:
    router = APIRouter()

    ACCEPT_INVITE_ROUTE_NAME = "accept_invitation"

    @router.get("/")
    async def list_workspaces(
        user: AuthenticatedUser, workspace_repository: WorkspaceRepositoryDependency
    ) -> List[WorkspaceRead]:
        """List all workspaces."""
        orgs = await workspace_repository.list_workspaces(user.id)

        return [WorkspaceRead.from_model(org) for org in orgs]

    @router.get("/{workspace_id}")
    async def get_workspace(
        workspace_id: WorkspaceId,
        user: AuthenticatedUser,
        workspace_repository: WorkspaceRepositoryDependency,
    ) -> WorkspaceRead | None:
        """Get a workspace."""
        org = await workspace_repository.get_workspace(workspace_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Workspace not found")

        if user.id not in org.all_users():
            raise HTTPException(status_code=403, detail="You are not a member of this workspace")

        return WorkspaceRead.from_model(org)

    @router.get("/{workspace_id}/settings")
    async def get_workspace_settings(
        workspace: UserWorkspaceDependency,
    ) -> WorkspaceSettingsRead:
        """Get a workspace."""
        return WorkspaceSettingsRead.from_model(workspace)

    @router.patch("/{workspace_id}/settings")
    async def update_workspace_settings(
        workspace: UserWorkspaceDependency,
        settings: WorkspaceSettingsUpdate,
        workspace_repository: WorkspaceRepositoryDependency,
    ) -> WorkspaceSettingsRead:
        """Update a workspace."""
        org = await workspace_repository.update_workspace(
            workspace_id=workspace.id,
            name=settings.name,
            generate_external_id=settings.generate_new_external_id,
        )
        return WorkspaceSettingsRead.from_model(org)

    @router.post("/")
    async def create_workspace(
        organization: WorkspaceCreate,
        user: AuthenticatedUser,
        workspace_repository: WorkspaceRepositoryDependency,
    ) -> WorkspaceRead:
        """Create a workspace."""
        try:
            org = await workspace_repository.create_workspace(
                name=organization.name, slug=organization.slug, owner=user
            )
        except IntegrityError:
            raise HTTPException(status_code=409, detail="Organization with this slug already exists")

        return WorkspaceRead.from_model(org)

    @router.get("/{workspace_id}/invites/")
    async def list_invites(
        workspace: UserWorkspaceDependency,
        invitation_repository: InvitationRepositoryDependency,
    ) -> List[WorkspaceInviteRead]:
        invites = await invitation_repository.list_invitations(workspace_id=workspace.id)

        return [
            WorkspaceInviteRead(
                organization_slug=workspace.slug,
                user_email=invite.email,
                expires_at=invite.expires_at,
            )
            for invite in invites
        ]

    @router.post("/{workspace_id}/invites/")
    async def invite_to_organization(
        workspace: UserWorkspaceDependency,
        user: AuthenticatedUser,
        user_email: EmailStr,
        invitation_service: InvitationServiceDependency,
        request: Request,
    ) -> WorkspaceInviteRead:
        """Invite a user to the workspace."""

        accept_invite_url = str(request.url_for(ACCEPT_INVITE_ROUTE_NAME, workspace_id=workspace.id))

        invite, _ = await invitation_service.invite_user(
            workspace_id=workspace.id, inviter=user, invitee=user_email, accept_invite_base_url=accept_invite_url
        )

        return WorkspaceInviteRead(
            organization_slug=workspace.slug,
            user_email=invite.email,
            expires_at=invite.expires_at,
        )

    @router.delete("/{workspace_id}/invites/{invite_id}")
    async def delete_invite(
        workspace: UserWorkspaceDependency,
        invite_id: InvitationId,
        invitation_repository: InvitationRepositoryDependency,
    ) -> None:
        """Delete invite."""
        await invitation_repository.delete_invitation(invite_id)

    @router.get("{workspace_id}/accept_invite", name=ACCEPT_INVITE_ROUTE_NAME)
    async def accept_invitation(
        token: str,
        invitation_service: InvitationServiceDependency,
    ) -> None:
        """Accept an invitation to the workspace."""
        await invitation_service.accept_invitation(token)

    @router.get("/{workspace_id}/cf_url")
    async def get_cf_url(
        workspace: UserWorkspaceDependency,
        config: ConfigDependency,
    ) -> str:
        return (
            f"https://console.aws.amazon.com/cloudformation/home#/stacks/create/review"
            f"?templateURL={config.cf_template_url}"
            "&stackName=FixAccess"
            f"&param_WorkspaceId={workspace.id}"
            f"&param_ExternalId={workspace.external_id}"
        )

    @router.get("/{workspace_id}/cf_template")
    async def get_cf_template(
        config: ConfigDependency,
    ) -> str:
        return config.cf_template_url

    @router.get("/{workspace_id}/external_id")
    async def get_external_id(
        workspace: UserWorkspaceDependency,
    ) -> ExternalIdRead:
        """Get a workspaces external id."""
        return ExternalIdRead(external_id=workspace.external_id)

    return router
