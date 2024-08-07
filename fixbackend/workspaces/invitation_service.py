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


from datetime import timedelta
from logging import getLogger
from typing import Annotated, Dict, Sequence, Tuple, Union
from attrs import frozen

import jwt
from attrs import evolve
from fastapi import Depends
from fastapi_users.jwt import decode_jwt, generate_jwt
from fixcloudutils.util import utc

from fixbackend.auth.models import User
from fixbackend.auth.user_repository import UserRepository, UserRepositoryDependency
from fixbackend.config import Config, ConfigDependency, ProductTierSettings
from fixbackend.dependencies import FixDependency, ServiceNames
from fixbackend.domain_events.dependencies import DomainEventPublisherDependency
from fixbackend.domain_events.events import InvitationAccepted
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.errors import NotAllowed, ResourceNotFound
from fixbackend.ids import InvitationId, WorkspaceId
from fixbackend.notification.email.email_messages import Invite
from fixbackend.notification.notification_service import NotificationService
from fixbackend.permissions.models import Roles
from fixbackend.workspaces.invitation_repository import InvitationRepository, InvitationRepositoryDependency
from fixbackend.workspaces.models import WorkspaceInvitation
from fixbackend.workspaces.repository import WorkspaceRepository, WorkspaceRepositoryDependency

log = getLogger(__name__)

STATE_TOKEN_AUDIENCE = "fix:invitation-state"


def generate_state_token(data: Dict[str, str], secret: str) -> str:
    data["aud"] = STATE_TOKEN_AUDIENCE
    return generate_jwt(data, secret, int(timedelta(days=7).total_seconds()))


@frozen
class InvitationNotFound:
    pass


@frozen
class NoFreeSeats:
    pass


@frozen
class WorkspaceNotFound:
    pass


InvitationError = Union[InvitationNotFound, NoFreeSeats, WorkspaceNotFound]


class InvitationService:
    def __init__(
        self,
        workspace_repository: WorkspaceRepository,
        invitation_repository: InvitationRepository,
        notification_service: NotificationService,
        user_repository: UserRepository,
        domain_events: DomainEventPublisher,
        config: Config,
    ) -> None:
        self.invitation_repository = invitation_repository
        self.notification_service = notification_service
        self.workspace_repository = workspace_repository
        self.user_repository = user_repository
        self.domain_events = domain_events
        self.config = config

    async def invite_user(
        self, workspace_id: WorkspaceId, inviter: User, invitee_email: str, accept_invite_base_url: str, role: Roles
    ) -> Tuple[WorkspaceInvitation, str]:
        workspace = await self.workspace_repository.get_workspace(workspace_id)
        if workspace is None:
            raise ResourceNotFound(f"Workspace {workspace_id} does not exist.")

        # check permissions
        settings = ProductTierSettings[workspace.current_product_tier()]
        if workspace.payment_on_hold_since:
            raise NotAllowed("payment_on_hold")
        if settings.seats_max and len(workspace.all_users()) >= settings.seats_max:
            raise NotAllowed("user_limit_reached")

        # this is idempotent and will return the existing invitation if it exists
        invitation = await self.invitation_repository.create_invitation(workspace_id, invitee_email, role)

        state_data: Dict[str, str] = {
            "invitation_id": str(invitation.id),
        }
        token = generate_state_token(state_data, secret=self.config.secret)

        invite_link = f"{accept_invite_base_url}?token={token}"
        message = Invite(inviter=inviter.email, invitation_link=invite_link, recipient=invitee_email)
        await self.notification_service.send_message(message=message, to=invitee_email)
        return invitation, token

    async def list_invitations(self, workspace_id: WorkspaceId) -> Sequence[WorkspaceInvitation]:
        return await self.invitation_repository.list_invitations(workspace_id)

    async def accept_invitation(self, token: str) -> WorkspaceInvitation | InvitationError:
        try:
            decoded_state = decode_jwt(token, self.config.secret, [STATE_TOKEN_AUDIENCE])
        except (jwt.ExpiredSignatureError, jwt.DecodeError) as ex:
            log.info(f"accept invitation callback: invalid state token: {token}, {ex}")
            raise NotAllowed("Invalid state token.", ex)

        invitation_id = decoded_state["invitation_id"]
        invitation = await self.invitation_repository.get_invitation(invitation_id)
        if invitation is None:
            return InvitationNotFound()

        workspace = await self.workspace_repository.get_workspace(invitation.workspace_id)
        if workspace is None:
            return WorkspaceNotFound()

        settings = ProductTierSettings[workspace.current_product_tier()]
        if workspace.payment_on_hold_since or (settings.seats_max and len(workspace.all_users()) >= settings.seats_max):
            return NoFreeSeats()

        updated = await self.invitation_repository.update_invitation(
            invitation_id, lambda invite: evolve(invite, accepted_at=utc())
        )

        # in case the user already exists, add it to the workspace and delete the invitation
        if user := await self.user_repository.get_by_email(invitation.email):
            await self.workspace_repository.add_to_workspace(invitation.workspace_id, user.id, invitation.role)
            await self.invitation_repository.delete_invitation(workspace.id, invitation_id)

        event = InvitationAccepted(invitation.workspace_id, user.id if user else None, invitation.email)
        await self.domain_events.publish(event)

        return updated

    async def revoke_invitation(self, workspace_id: WorkspaceId, invitation_id: InvitationId) -> None:
        await self.invitation_repository.delete_invitation(workspace_id, invitation_id)


def get_invitation_service(
    workspace_repository: WorkspaceRepositoryDependency,
    invitation_repository: InvitationRepositoryDependency,
    user_repository: UserRepositoryDependency,
    domain_events: DomainEventPublisherDependency,
    deps: FixDependency,
    config: ConfigDependency,
) -> InvitationService:
    return InvitationService(
        workspace_repository=workspace_repository,
        invitation_repository=invitation_repository,
        notification_service=deps.service(ServiceNames.notification_service, NotificationService),
        user_repository=user_repository,
        domain_events=domain_events,
        config=config,
    )


InvitationServiceDependency = Annotated[InvitationService, Depends(get_invitation_service)]
