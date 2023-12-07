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

from typing import Callable, List, Optional, Sequence, Tuple

import pytest
from fastapi import Request, FastAPI
from httpx import AsyncClient

from fixbackend.auth.models import User
from fixbackend.auth.user_verifier import UserVerifier, get_user_verifier
from fixbackend.auth.auth_backend import session_cookie_name
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.domain_events.dependencies import get_domain_event_publisher
from fixbackend.domain_events.events import Event, UserRegistered, WorkspaceCreated
from fixbackend.ids import InvitationId, WorkspaceId
from fixbackend.workspaces.invitation_repository import InvitationRepository, get_invitation_repository
from fixbackend.workspaces.models import WorkspaceInvitation

from tests.fixbackend.conftest import InMemoryDomainEventPublisher


class InMemoryVerifier(UserVerifier):
    def __init__(self) -> None:
        self.verification_requests: List[Tuple[User, str]] = []

    async def verify(self, user: User, token: str, request: Optional[Request]) -> None:
        return self.verification_requests.append((user, token))


class InMemoryDomainSender(DomainEventPublisher):
    def __init__(self) -> None:
        self.events: List[Event] = []

    async def publish(self, event: Event) -> None:
        return self.events.append(event)


class InMemoryInvitationRepo(InvitationRepository):
    async def get_invitation_by_email(self, email: str) -> Optional[WorkspaceInvitation]:
        return None

    async def create_invitation(self, workspace_id: WorkspaceId, email: str) -> WorkspaceInvitation:
        """Create an invite for a workspace."""
        raise NotImplementedError

    async def get_invitation(self, invitation_id: InvitationId) -> Optional[WorkspaceInvitation]:
        """Get an invitation by ID."""
        raise NotImplementedError

    async def list_invitations(self, workspace_id: WorkspaceId) -> Sequence[WorkspaceInvitation]:
        """List all invitations for a workspace."""
        raise NotImplementedError

    async def update_invitation(
        self,
        invitation_id: InvitationId,
        update_fn: Callable[[WorkspaceInvitation], WorkspaceInvitation],
    ) -> WorkspaceInvitation:
        """Update an invitation."""
        raise NotImplementedError

    async def delete_invitation(self, invitation_id: InvitationId) -> None:
        """Delete an invitation."""
        raise NotImplementedError


@pytest.mark.asyncio
async def test_registration_flow(
    api_client: AsyncClient, fast_api: FastAPI, domain_event_sender: InMemoryDomainEventPublisher
) -> None:
    verifier = InMemoryVerifier()
    invitation_repo = InMemoryInvitationRepo()
    fast_api.dependency_overrides[get_user_verifier] = lambda: verifier
    fast_api.dependency_overrides[get_domain_event_publisher] = lambda: domain_event_sender
    fast_api.dependency_overrides[get_invitation_repository] = lambda: invitation_repo

    registration_json = {
        "email": "user@example.com",
        "password": "changeme",
    }

    # register user
    response = await api_client.post("/api/auth/register", json=registration_json)
    assert response.status_code == 201

    login_json = {
        "username": registration_json["email"],
        "password": registration_json["password"],
    }

    # non_verified can't login
    response = await api_client.post("/api/auth/jwt/login", data=login_json)
    assert response.status_code == 400

    # verify user
    user, token = verifier.verification_requests[0]
    verification_json = {
        "token": token,
    }
    response = await api_client.post("/api/auth/verify", json=verification_json)
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["email"] == user.email
    assert response_json["is_superuser"] is False
    assert response_json["is_verified"] is True
    assert response_json["is_active"] is True
    assert response_json["id"] == str(user.id)

    # verified can login
    response = await api_client.post("/api/auth/jwt/login", data=login_json)
    assert response.status_code == 204
    auth_cookie = response.cookies.get(session_cookie_name)
    assert auth_cookie is not None

    # organization is created by default
    response = await api_client.get("/api/workspaces/", cookies={session_cookie_name: auth_cookie})
    workspace_json = response.json()[0]
    assert workspace_json.get("name") == user.email

    # domain event is sent
    assert len(domain_event_sender.events) == 2
    event = domain_event_sender.events[1]
    assert isinstance(event, UserRegistered)
    assert event.user_id == user.id
    assert event.email == user.email
    assert str(event.tenant_id) == workspace_json["id"]

    event1 = domain_event_sender.events[0]
    assert isinstance(event1, WorkspaceCreated)
    assert str(event1.workspace_id) == workspace_json["id"]
