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

from fixbackend.auth.depedencies import AuthenticatedUser
from fixbackend.auth.user_manager import UserManagerDependency
from fixbackend.config import ConfigDependency
from fixbackend.ids import WorkspaceId
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
            raise HTTPException(status_code=404, detail="Organization not found")

        if user.id not in org.all_users():
            raise HTTPException(status_code=403, detail="You are not an owner of this organization")

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
        workspace_repository: WorkspaceRepositoryDependency,
    ) -> List[WorkspaceInviteRead]:
        invites = await workspace_repository.list_invitations(workspace_id=workspace.id)

        return [
            WorkspaceInviteRead(
                organization_slug=workspace.slug,
                user_id=invite.user_id,
                expires_at=invite.expires_at,
            )
            for invite in invites
        ]

    @router.post("/{workspace_id}/invites/")
    async def invite_to_organization(
        workspace: UserWorkspaceDependency,
        user_email: EmailStr,
        workspace_repository: WorkspaceRepositoryDependency,
        user_manager: UserManagerDependency,
    ) -> WorkspaceInviteRead:
        """Invite a user to the workspace."""

        user = await user_manager.get_by_email(user_email)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        invite = await workspace_repository.create_invitation(workspace_id=workspace.id, user_id=user.id)

        return WorkspaceInviteRead(
            organization_slug=workspace.slug,
            user_id=user.id,
            expires_at=invite.expires_at,
        )

    @router.delete("/{workspace_id}/invites/{invite_id}")
    async def delete_invite(
        workspace: UserWorkspaceDependency,
        invite_id: UUID,
        workspace_repository: WorkspaceRepositoryDependency,
    ) -> None:
        """Delete invite."""
        await workspace_repository.delete_invitation(invite_id)

    @router.get("{workspace_id}/invites/{invite_id}/accept")
    async def accept_invitation(
        workspace_id: WorkspaceId,
        invite_id: UUID,
        user: AuthenticatedUser,
        workspace_repository: WorkspaceRepositoryDependency,
    ) -> None:
        """Accept an invitation to the workspace."""
        org = await workspace_repository.get_workspace(workspace_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        invite = await workspace_repository.get_invitation(invite_id)
        if invite is None:
            raise HTTPException(status_code=404, detail="Invitation not found")

        if user.id != invite.user_id:
            raise HTTPException(status_code=403, detail="You can only accept invitations for your own account")

        await workspace_repository.accept_invitation(invite_id)

        return None

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
