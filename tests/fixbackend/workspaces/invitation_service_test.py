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

import pytest
from fixcloudutils.util import utc

from fixbackend.auth.models import User
from fixbackend.auth.user_repository import UserRepository
from fixbackend.config import Config
from fixbackend.domain_events.events import InvitationAccepted, UserJoinedWorkspace
from fixbackend.errors import NotAllowed
from fixbackend.ids import ProductTier
from fixbackend.notification.email.email_messages import EmailMessage, Invite
from fixbackend.notification.notification_service import NotificationService
from fixbackend.permissions.models import Roles
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.workspaces.invitation_repository import InvitationRepository
from fixbackend.workspaces.invitation_service import (
    InvitationNotFound,
    InvitationService,
    InvitationServiceImpl,
    NoFreeSeats,
)
from fixbackend.workspaces.repository import WorkspaceRepository
from fixbackend.permissions.role_repository import RoleRepository
from tests.fixbackend.conftest import InMemoryDomainEventPublisher


# noinspection PyMissingConstructor
class NotificationServiceMock(NotificationService):
    def __init__(self) -> None:
        self.call_args: List[EmailMessage] = []

    async def send_email(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        html: Optional[str],
    ) -> None:
        pass

    async def send_message(self, *, to: str, message: EmailMessage) -> None:
        self.call_args.append(message)


@pytest.fixture
def notification_service() -> NotificationServiceMock:
    return NotificationServiceMock()


@pytest.fixture
def service(
    workspace_repository: WorkspaceRepository,
    invitation_repository: InvitationRepository,
    notification_service: NotificationService,
    user_repository: UserRepository,
    domain_event_sender: InMemoryDomainEventPublisher,
    default_config: Config,
) -> InvitationService:
    return InvitationServiceImpl(
        workspace_repository=workspace_repository,
        invitation_repository=invitation_repository,
        notification_service=notification_service,
        user_repository=user_repository,
        domain_events=domain_event_sender,
        config=default_config,
    )


@pytest.mark.asyncio
async def test_invite_accept_user(
    service: InvitationService,
    workspace_repository: WorkspaceRepository,
    invitation_repository: InvitationRepository,
    notification_service: NotificationServiceMock,
    user_repository: UserRepository,
    domain_event_sender: InMemoryDomainEventPublisher,
    role_repository: RoleRepository,
    user: User,
    aws_marketplace_subscription: AwsMarketplaceSubscription,
) -> None:
    workspace = await workspace_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )

    new_user_email = "new@foo.com"

    await workspace_repository.update_subscription(workspace.id, aws_marketplace_subscription.id)

    # invite can't be done if the workspace has payment on hold
    await workspace_repository.update_payment_on_hold(workspace.id, utc())
    with pytest.raises(NotAllowed):
        await service.invite_user(
            workspace.id, user, new_user_email, "https://example.com", Roles.workspace_billing_admin
        )
    await workspace_repository.update_payment_on_hold(workspace.id, None)

    # can invite a new user on a better tier
    workspace = await workspace_repository.update_product_tier(workspace.id, ProductTier.Plus)
    invite, _ = await service.invite_user(
        workspace.id, user, new_user_email, "https://example.com", Roles.workspace_billing_admin
    )
    assert await invitation_repository.list_invitations(workspace.id) == [invite]
    assert invite.role == Roles.workspace_billing_admin

    # idempotency
    second_invite, _ = await service.invite_user(
        workspace.id, user, new_user_email, "https://example.com", Roles.workspace_billing_admin
    )
    assert second_invite == invite

    # list invitations
    assert await invitation_repository.list_invitations(workspace.id) == [invite]

    # check email
    email = notification_service.call_args[0]
    assert isinstance(email, Invite)
    assert email.recipient == new_user_email
    assert email.subject() == "You've been invited to join a Fix workspace"
    assert email.text().startswith(f"{user.email} has invited you to join their workspace")
    assert "https://example.com?token=" in email.text()

    # existing user
    existing_user = await user_repository.create(
        {
            "email": "existing@foo.com",
            "hashed_password": "notreallyhashed",
            "is_verified": True,
        }
    )
    existing_invite, token = await service.invite_user(
        workspace.id, user, existing_user.email, "https://example.com", Roles.workspace_billing_admin
    )

    # accepting the invite should fail if there are not enough seats
    await workspace_repository.update_product_tier(workspace.id, ProductTier.Free)
    assert await service.accept_invitation(token) == NoFreeSeats()

    # revert to the previous tier
    await workspace_repository.update_product_tier(workspace.id, ProductTier.Plus)

    # accepting the invite should fail if the workspace has payment on hold
    await workspace_repository.update_payment_on_hold(workspace.id, utc())
    assert await service.accept_invitation(token) == NoFreeSeats()
    await workspace_repository.update_payment_on_hold(workspace.id, None)

    # when the existinng user accepts the invite, they should be added to the workspace automatically
    # and the invitation should be deleted
    await service.accept_invitation(token)
    assert list(map(lambda w: w.id, await workspace_repository.list_workspaces(existing_user))) == [workspace.id]
    assert await service.list_invitations(workspace.id) == [invite]
    assert len(domain_event_sender.events) == 3
    user_joined = domain_event_sender.events[1]
    assert isinstance(user_joined, UserJoinedWorkspace)
    assert user_joined.workspace_id == workspace.id
    assert user_joined.user_id == existing_user.id
    accepted = domain_event_sender.events[2]
    assert isinstance(accepted, InvitationAccepted)
    assert accepted.workspace_id == workspace.id
    assert accepted.user_id == existing_user.id

    # role is correct after the user accepts the invite
    user_roles = await role_repository.list_roles(existing_user.id)
    assert len(user_roles) == 1
    assert user_roles[0].role_names == Roles.workspace_billing_admin

    # accepting the invite again returns NotFound
    assert await service.accept_invitation(token) == InvitationNotFound()

    # invite can be revoked
    await service.revoke_invitation(invite.id)
    assert await service.list_invitations(workspace.id) == []

    # invalid token is rejected
    with pytest.raises(NotAllowed):
        await service.accept_invitation("invalid token")
