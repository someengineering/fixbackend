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

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError

from fixbackend.auth.depedencies import AuthenticatedUser
from fixbackend.auth.models import User
from fixbackend.auth.user_repository import UserRepositoryDependency
from fixbackend.config import ConfigDependency
from fixbackend.ids import InvitationId, SubscriptionId, UserId, WorkspaceId, SecurityTier
from fixbackend.subscription.subscription_repository import SubscriptionRepositoryDependency
from fixbackend.workspaces.invitation_service import InvitationServiceDependency
from fixbackend.workspaces.repository import WorkspaceRepositoryDependency
from fixbackend.workspaces.dependencies import UserWorkspaceDependency
from fixbackend.workspaces.schemas import (
    ExternalIdRead,
    UserInvite,
    WorkspaceBilling,
    WorkspaceCreate,
    WorkspaceInviteRead,
    WorkspaceRead,
    WorkspaceSettingsRead,
    WorkspaceSettingsUpdate,
    WorkspaceUserRead,
    SecurityTierJson,
)
from fixbackend.errors import ResourceNotFound
import asyncio


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
        invitation_service: InvitationServiceDependency,
    ) -> List[WorkspaceInviteRead]:
        invites = await invitation_service.list_invitations(workspace_id=workspace.id)

        return [WorkspaceInviteRead.from_model(invite, workspace) for invite in invites]

    @router.get("/{workspace_id}/users/")
    async def list_users(
        workspace: UserWorkspaceDependency,
        user_repository: UserRepositoryDependency,
    ) -> List[WorkspaceUserRead]:
        user_ids = workspace.all_users()
        users: List[Optional[User]] = await asyncio.gather(*[user_repository.get(user_id) for user_id in user_ids])
        return [WorkspaceUserRead.from_model(user) for user in users if user]

    @router.post("/{workspace_id}/invites/")
    async def invite_to_organization(
        workspace: UserWorkspaceDependency,
        user: AuthenticatedUser,
        user_invite: UserInvite,
        invitation_service: InvitationServiceDependency,
        request: Request,
    ) -> WorkspaceInviteRead:
        """Invite a user to the workspace."""

        accept_invite_url = str(request.url_for(ACCEPT_INVITE_ROUTE_NAME, workspace_id=workspace.id))

        invite, _ = await invitation_service.invite_user(
            workspace_id=workspace.id,
            inviter=user,
            invitee_email=user_invite.email,
            accept_invite_base_url=accept_invite_url,
        )

        return WorkspaceInviteRead.from_model(invite, workspace)

    @router.delete("/{workspace_id}/users/{user_id}/")
    async def remove_user(
        workspace: UserWorkspaceDependency,
        user_id: UserId,
        workspace_repository: WorkspaceRepositoryDependency,
        user_repository: UserRepositoryDependency,
    ) -> None:
        """Delete a user from the workspace."""
        user = await user_repository.get(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        await workspace_repository.remove_from_workspace(workspace_id=workspace.id, user_id=user.id)

    @router.delete("/{workspace_id}/invites/{invite_id}")
    async def delete_invite(
        workspace: UserWorkspaceDependency,
        invite_id: InvitationId,
        invitation_service: InvitationServiceDependency,
    ) -> None:
        """Delete invite."""
        await invitation_service.revoke_invitation(invite_id)

    @router.get("{workspace_id}/accept_invite", name=ACCEPT_INVITE_ROUTE_NAME)
    async def accept_invitation(
        token: str, invitation_service: InvitationServiceDependency, request: Request
    ) -> Response:
        """Accept an invitation to the workspace."""
        invitation = await invitation_service.accept_invitation(token)
        url = request.base_url.replace_query_params(message="invitation-accepted", workspace_id=invitation.workspace_id)
        return RedirectResponse(url)

    @router.get("/{workspace_id}/billing")
    async def get_billing(workspace: UserWorkspaceDependency) -> WorkspaceBilling:
        """Get a workspace billing."""
        return WorkspaceBilling.from_model(workspace)

    @router.put("/{workspace_id}/billing")
    async def update_billing(
        workspace: UserWorkspaceDependency,
        workspace_repository: WorkspaceRepositoryDependency,
        billing: WorkspaceBilling,
    ) -> WorkspaceBilling:
        """Update a workspace billing."""

        def tier(billing: WorkspaceBilling) -> SecurityTier:
            match billing.security_tier:
                case SecurityTierJson.Free:
                    return SecurityTier.Free
                case SecurityTierJson.Foundational:
                    return SecurityTier.Foundational
                case SecurityTierJson.HighSecurity:
                    return SecurityTier.HighSecurity

        org = await workspace_repository.update_security_tier(
            workspace_id=workspace.id,
            security_tier=tier(billing),
        )
        return WorkspaceBilling.from_model(org)

    @router.put("/{workspace_id}/subscription/{subscription_id}")
    async def assign_subscription(
        workspace: UserWorkspaceDependency,
        user: AuthenticatedUser,
        subscription_repository: SubscriptionRepositoryDependency,
        subscription_id: SubscriptionId,
    ) -> None:
        """Assign a subscription to a workspace."""
        if not await subscription_repository.user_has_subscription(user.id, subscription_id):
            raise ResourceNotFound("Subscription not found")

        await subscription_repository.update_workspace(subscription_id, workspace.id)

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
