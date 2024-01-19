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


from typing import Optional, List
import pytest
from fixbackend.domain_events.events import InvitationAccepted, UserJoinedWorkspace
from fixbackend.notification.messages import EmailMessage, Invite
from fixbackend.workspaces.invitation_service import InvitationService, InvitationServiceImpl


from fixbackend.workspaces.repository import WorkspaceRepository
from fixbackend.workspaces.invitation_repository import InvitationRepository
from fixbackend.notification.service import NotificationService
from fixbackend.auth.user_repository import UserRepository
from fixbackend.config import Config
from fixbackend.auth.models import User
from tests.fixbackend.conftest import InMemoryDomainEventPublisher


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
    user: User,
) -> None:
    workspace = await workspace_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )

    new_user_email = "new@foo.com"

    # invite new user
    invite, _ = await service.invite_user(workspace.id, user, new_user_email, "https://example.com")
    assert await invitation_repository.list_invitations(workspace.id) == [invite]

    # idempotency
    second_invite, _ = await service.invite_user(workspace.id, user, new_user_email, "https://example.com")
    assert second_invite == invite

    # list invitations
    assert await invitation_repository.list_invitations(workspace.id) == [invite]

    # check email
    email = notification_service.call_args[0]
    assert isinstance(email, Invite)
    assert email.recipient == new_user_email
    assert email.subject() == "You've been invited to join FIX!"
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
    existing_invite, token = await service.invite_user(workspace.id, user, existing_user.email, "https://example.com")

    # when the existinng user accepts the invite, they should be added to the workspace automatically
    # and the invitation should be deleted
    await service.accept_invitation(token)
    assert list(map(lambda w: w.id, await workspace_repository.list_workspaces(existing_user.id))) == [workspace.id]
    assert await service.list_invitations(workspace.id) == [invite]
    assert len(domain_event_sender.events) == 3
    assert domain_event_sender.events[1] == UserJoinedWorkspace(workspace.id, existing_user.id)
    assert domain_event_sender.events[2] == InvitationAccepted(workspace.id, existing_user.id, existing_user.email)

    # invite can be revoked
    await service.revoke_invitation(invite.id)
    assert await service.list_invitations(workspace.id) == []

    # invalid token is rejected
    with pytest.raises(ValueError):
        await service.accept_invitation("invalid token")
