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

from typing import Callable, List, Optional, Sequence, Tuple, override
import jwt

import pytest
from fastapi import Request, FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.auth.models import UserRoles, RoleName, User, workspace_owner_permissions
from fixbackend.auth.role_repository import RoleRepository, get_role_repository
from fixbackend.auth.user_verifier import AuthEmailSender, get_auth_email_sender
from fixbackend.auth.auth_backend import session_cookie_name
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.domain_events.dependencies import get_domain_event_publisher
from fixbackend.domain_events.events import Event, UserRegistered, WorkspaceCreated
from fixbackend.ids import InvitationId, UserRoleId, UserId, WorkspaceId
from fixbackend.workspaces.invitation_repository import InvitationRepository, get_invitation_repository
from fixbackend.workspaces.models import WorkspaceInvitation
from fixbackend.workspaces.repository import WorkspaceRepository

from tests.fixbackend.conftest import InMemoryDomainEventPublisher
import uuid


class InMemoryVerifier(AuthEmailSender):
    def __init__(self) -> None:
        self.verification_requests: List[Tuple[User, str]] = []

    async def send_verify_email(self, user: User, token: str, request: Optional[Request]) -> None:
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


class InMemoryRoleRepository(RoleRepository):
    def __init__(self) -> None:
        self.roles: List[UserRoles] = []

    @override
    async def list_roles(self, user_id: UserId) -> List[UserRoles]:
        return self.roles

    @override
    async def add_roles(
        self, user_id: UserId, workspace_id: WorkspaceId, roles: RoleName, *, session: Optional[AsyncSession] = None
    ) -> None:
        pass
        self.roles.append(UserRoles(UserRoleId(uuid.uuid4()), user_id, workspace_id, roles))

    @override
    async def remove_roles(
        self, user_id: UserId, workspace_id: WorkspaceId, roles: RoleName, *, session: Optional[AsyncSession] = None
    ) -> None:
        pass


@pytest.mark.asyncio
async def test_registration_flow(
    api_client: AsyncClient,
    fast_api: FastAPI,
    domain_event_sender: InMemoryDomainEventPublisher,
    workspace_repository: WorkspaceRepository,
) -> None:
    verifier = InMemoryVerifier()
    invitation_repo = InMemoryInvitationRepo()
    role_repo = InMemoryRoleRepository()
    fast_api.dependency_overrides[get_auth_email_sender] = lambda: verifier
    fast_api.dependency_overrides[get_domain_event_publisher] = lambda: domain_event_sender
    fast_api.dependency_overrides[get_invitation_repository] = lambda: invitation_repo
    fast_api.dependency_overrides[get_role_repository] = lambda: role_repo

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

    # workspace is created
    workspaces = await workspace_repository.list_workspaces(user.id)
    assert len(workspaces) == 1
    workspace = workspaces[0]
    await role_repo.add_roles(user.id, workspace.id, RoleName.workspace_owner)

    # verified can login
    response = await api_client.post("/api/auth/jwt/login", data=login_json)
    assert response.status_code == 204
    auth_cookie = response.cookies.get(session_cookie_name)
    assert auth_cookie is not None

    # role is set on login
    auth_token = jwt.api_jwt.decode_complete(auth_cookie, options={"verify_signature": False})
    assert auth_token["payload"]["permissions"] == {str(workspace.id): workspace_owner_permissions.value}

    # workspace can be listed
    response = await api_client.get("/api/workspaces/", cookies={session_cookie_name: auth_cookie})
    workspace_json = response.json()[0]
    assert workspace_json.get("name") == user.email

    # workspace can be viewed by an owner
    response = await api_client.get(f"/api/workspaces/{workspace.id}", cookies={session_cookie_name: auth_cookie})
    assert response.status_code == 200
    workspace_json = response.json()
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
