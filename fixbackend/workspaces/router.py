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

from functools import reduce
from typing import Annotated, List, Union

from disposable_email_domains import blocklist
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from starlette import status

from fixbackend.auth.depedencies import AuthenticatedUser
from fixbackend.permissions.models import WorkspacePermissions, Roles
from fixbackend.permissions.permission_checker import WorkspacePermissionChecker
from fixbackend.auth.user_repository import UserRepositoryDependency
from fixbackend.config import ConfigDependency
from fixbackend.ids import InvitationId, UserId, WorkspaceId
from fixbackend.workspaces.invitation_service import (
    InvitationServiceDependency,
    InvitationNotFound,
    WorkspaceNotFound,
    NoFreeSeats,
)
from fixbackend.workspaces.models import Workspace, WorkspaceInvitation
from fixbackend.workspaces.repository import WorkspaceRepositoryDependency
from fixbackend.workspaces.dependencies import UserWorkspaceDependency, WorkspaceError, get_optional_user_workspace
from fixbackend.workspaces.schemas import (
    ExternalIdRead,
    UserInvite,
    WorkspaceCreate,
    WorkspaceInviteRead,
    WorkspaceRead,
    WorkspaceRoleListRead,
    WorkspaceSettingsRead,
    WorkspaceSettingsUpdate,
    WorkspaceUserRead,
)


def workspaces_router() -> APIRouter:
    router = APIRouter()

    ACCEPT_INVITE_ROUTE_NAME = "accept_invitation"

    @router.get("/")
    async def list_workspaces(
        user: AuthenticatedUser,
        workspace_repository: WorkspaceRepositoryDependency,
        can_assign_subscriptions: bool = False,
    ) -> List[WorkspaceRead]:
        """List all workspaces."""
        workspaces = await workspace_repository.list_workspaces(user)
        result = []
        user_roles_dict = {role.workspace_id: role for role in user.roles}
        for ws in workspaces:
            result.append(WorkspaceRead.from_model(ws, user.id, user_roles_dict.get(ws.id)))

        return result

    @router.get("/{workspace_id}")
    async def get_workspace(
        workspace_id: WorkspaceId,
        user: AuthenticatedUser,
        workspace_repository: WorkspaceRepositoryDependency,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.read))],
    ) -> WorkspaceRead | None:
        """Get a workspace."""
        org = await workspace_repository.get_workspace(workspace_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Workspace not found")

        if user.id not in org.all_users():
            raise HTTPException(status_code=403, detail="You are not a member of this workspace")

        roles = next(filter(lambda role: role.workspace_id == org.id, user.roles), None)

        return WorkspaceRead.from_model(org, user.id, roles)

    @router.get("/{workspace_id}/settings")
    async def get_workspace_settings(
        workspace: UserWorkspaceDependency,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.read_settings))],
    ) -> WorkspaceSettingsRead:
        """Get a workspace."""
        return WorkspaceSettingsRead.from_model(workspace)

    @router.patch("/{workspace_id}/settings")
    async def update_workspace_settings(
        workspace: UserWorkspaceDependency,
        settings: WorkspaceSettingsUpdate,
        workspace_repository: WorkspaceRepositoryDependency,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update_settings))],
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
        user_repository: UserRepositoryDependency,
    ) -> WorkspaceRead:
        """Create a workspace."""
        try:
            org = await workspace_repository.create_workspace(
                name=organization.name, slug=organization.slug, owner=user
            )
        except IntegrityError:
            raise HTTPException(status_code=409, detail="Organization with this slug already exists")

        updated_user = await user_repository.get(user.id)
        if updated_user is None:
            raise ValueError("User not found, this should never happer, go fix this bug")

        roles = next(
            filter(lambda role: role.workspace_id == org.id, updated_user.roles),
            None,
        )

        return WorkspaceRead.from_model(org, user.id, roles)

    @router.get("/{workspace_id}/invites/")
    async def list_invites(
        workspace: UserWorkspaceDependency,
        invitation_service: InvitationServiceDependency,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.read))],
    ) -> List[WorkspaceInviteRead]:
        invites = await invitation_service.list_invitations(workspace_id=workspace.id)

        return [WorkspaceInviteRead.from_model(invite, workspace) for invite in invites]

    @router.get("/{workspace_id}/roles/")
    async def list_roles(
        workspace: UserWorkspaceDependency,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.read))],
    ) -> WorkspaceRoleListRead:

        all_roles = reduce(lambda x, y: x | y, Roles, Roles(0))  # type: ignore

        return WorkspaceRoleListRead.from_model(all_roles)

    @router.get("/{workspace_id}/users/")
    async def list_users(
        workspace: UserWorkspaceDependency,
        user_repository: UserRepositoryDependency,
        _: bool = Depends(WorkspacePermissionChecker(WorkspacePermissions.read)),
    ) -> List[WorkspaceUserRead]:
        user_ids = workspace.all_users()
        users = await user_repository.get_by_ids(user_ids)
        return [WorkspaceUserRead.from_model(user, workspace.id) for user in users]

    @router.post("/{workspace_id}/invites/")
    async def invite_to_organization(
        workspace: UserWorkspaceDependency,
        user: AuthenticatedUser,
        user_invite: UserInvite,
        invitation_service: InvitationServiceDependency,
        request: Request,
        authorized: bool = Depends(WorkspacePermissionChecker(WorkspacePermissions.invite_to)),
    ) -> WorkspaceInviteRead:
        """Invite a user to the workspace."""

        accept_invite_url = str(request.url_for(ACCEPT_INVITE_ROUTE_NAME, workspace_id=workspace.id))

        role = reduce(lambda acc, role_name: role_name.to_role() | acc, user_invite.roles, Roles.workspace_member)

        # make sure the email does not belong to a disposable domain
        if user.email.lower().split("@")[-1] in blocklist:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Disposable email domains are not allowed",
            )

        # create invitation
        invite, _ = await invitation_service.invite_user(
            workspace_id=workspace.id,
            inviter=user,
            invitee_email=user_invite.email,
            accept_invite_base_url=accept_invite_url,
            role=role,
        )

        return WorkspaceInviteRead.from_model(invite, workspace)

    @router.delete("/{workspace_id}/users/{user_id}/")
    async def remove_user(
        workspace: UserWorkspaceDependency,
        user_id: UserId,
        workspace_repository: WorkspaceRepositoryDependency,
        user_repository: UserRepositoryDependency,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.remove_from))],
    ) -> None:
        """Delete a user from the workspace."""
        user = await user_repository.get(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        if user_id == workspace.owner_id:
            raise HTTPException(status_code=403, detail="Cannot remove the owner of the workspace")
        await workspace_repository.remove_from_workspace(workspace_id=workspace.id, user_id=user.id)

    @router.delete("/{workspace_id}/invites/{invite_id}")
    async def delete_invite(
        workspace: UserWorkspaceDependency,
        invite_id: InvitationId,
        invitation_service: InvitationServiceDependency,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update))],
    ) -> None:
        """Delete invite."""
        await invitation_service.revoke_invitation(invite_id)

    @router.get("/{workspace_id}/accept_invite", name=ACCEPT_INVITE_ROUTE_NAME)
    async def accept_invitation(
        token: str,
        workspace_id: WorkspaceId,
        invitation_service: InvitationServiceDependency,
        request: Request,
        maybe_workspace: Annotated[Union[Workspace, WorkspaceError], Depends(get_optional_user_workspace)],
    ) -> Response:
        """Accept an invitation to the workspace."""
        invitation_result = await invitation_service.accept_invitation(token)
        match invitation_result:
            case InvitationNotFound():
                if isinstance(maybe_workspace, Workspace):
                    workspace_id = maybe_workspace.id
                    message = "invitation-accepted"
                else:
                    message = "invitation-not-found"
            case WorkspaceNotFound():
                message = "workspace-not-found"
            case NoFreeSeats():
                message = "no-free-seats"
            case WorkspaceInvitation():
                message = "invitation-accepted"
                workspace_id = invitation_result.workspace_id

        url = str(request.base_url.replace_query_params(message=message))
        url = url + f"#{workspace_id}"
        return RedirectResponse(url)

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
