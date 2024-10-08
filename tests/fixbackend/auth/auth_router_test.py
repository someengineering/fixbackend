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
import time
from typing import Callable, List, Optional, Sequence, Tuple, override

import jwt
import pytest
from fastapi import Request, FastAPI
from fastapi_users.password import PasswordHelper
from fixcloudutils.types import Json
from fixcloudutils.util import utc
from httpx import AsyncClient
from pyotp import TOTP
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.auth.auth_backend import SessionCookie, FixJWTStrategy
from fixbackend.auth.models import User
from fixbackend.auth.models.orm import UserMFARecoveryCode
from fixbackend.auth.schemas import OTPConfig
from fixbackend.auth.user_manager import UserManager
from fixbackend.auth.user_repository import UserRepository
from fixbackend.auth.user_verifier import AuthEmailSender
from fixbackend.certificates.cert_store import CertificateStore
from fixbackend.dependencies import FixDependencies, ServiceNames as SN
from fixbackend.domain_events.events import Event, UserRegistered, WorkspaceCreated
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.ids import InvitationId, UserId, WorkspaceId
from fixbackend.permissions.models import UserRole, Roles, workspace_owner_permissions
from fixbackend.permissions.role_repository import RoleRepository
from fixbackend.workspaces.invitation_repository import InvitationRepository
from fixbackend.workspaces.models import WorkspaceInvitation
from fixbackend.workspaces.repository import WorkspaceRepository
from tests.fixbackend.conftest import InMemoryDomainEventPublisher, InsecureFastPasswordHelper


class InMemoryVerifier(AuthEmailSender):
    # noinspection PyMissingConstructor
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

    def __init__(self) -> None:  # noqa
        pass

    async def get_invitation_by_email(self, email: str) -> Optional[WorkspaceInvitation]:
        return None

    async def create_invitation(self, workspace_id: WorkspaceId, email: str, role: Roles) -> WorkspaceInvitation:
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


class InMemoryRoleRepository(RoleRepository):
    def __init__(self) -> None:  # noqa
        self.roles: List[UserRole] = []

    @override
    async def list_roles(self, user_id: UserId) -> List[UserRole]:
        return self.roles

    @override
    async def list_roles_by_workspace_id(self, workspace_id: WorkspaceId) -> List[UserRole]:
        return self.roles

    @override
    async def add_roles(
        self,
        user_id: UserId,
        workspace_id: WorkspaceId,
        roles: Roles,
        *,
        session: Optional[AsyncSession] = None,
        replace_existing: bool = False,
    ) -> UserRole:
        role = UserRole(user_id, workspace_id, roles)
        self.roles.append(role)
        return role

    @override
    async def remove_roles(
        self, user_id: UserId, workspace_id: WorkspaceId, roles: Roles, *, session: Optional[AsyncSession] = None
    ) -> None:
        pass


@pytest.fixture
async def user_manager(
    api_client: AsyncClient,
    fast_api: FastAPI,
    domain_event_sender: InMemoryDomainEventPublisher,
    workspace_repository: WorkspaceRepository,
    user_repository: UserRepository,
    cert_store: CertificateStore,
    password_helper: InsecureFastPasswordHelper,
    fix_deps: FixDependencies,
) -> UserManager:
    verifier = fix_deps.add(SN.auth_email_sender, InMemoryVerifier())
    invitation_repo = fix_deps.add(SN.invitation_repository, InMemoryInvitationRepo())
    return fix_deps.add(
        SN.user_manager,
        UserManager(
            fix_deps.config,
            user_repository,
            password_helper,
            verifier,
            workspace_repository,
            domain_event_sender,
            invitation_repo,
        ),
    )


async def register_user(fix_deps: FixDependencies, api_client: AsyncClient) -> Tuple[User, Json, str]:
    verifier = fix_deps.service(SN.auth_email_sender, InMemoryVerifier)
    registration_json = {
        "email": "user@example.com",
        "password": "changeMe123456789",
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
    auth_cookie = response.cookies.get(SessionCookie)
    assert auth_cookie is not None

    return user, login_json, auth_cookie


@pytest.mark.asyncio
async def test_registration_flow(
    api_client: AsyncClient,
    fast_api: FastAPI,
    domain_event_sender: InMemoryDomainEventPublisher,
    workspace_repository: WorkspaceRepository,
    user_repository: UserRepository,
    cert_store: CertificateStore,
    user_manager: UserManager,
    jwt_strategy: FixJWTStrategy,
    fix_deps: FixDependencies,
) -> None:
    user_manager.password_helper = PasswordHelper()
    role_repo = fix_deps.add(SN.role_repository, InMemoryRoleRepository())
    user, login_json, auth_cookie = await register_user(fix_deps, api_client)

    # workspace is created
    workspaces = await workspace_repository.list_workspaces(user)
    assert len(workspaces) == 1
    workspace = workspaces[0]
    await role_repo.add_roles(user.id, workspace.id, Roles.workspace_owner)

    # role is set on login
    auth_token = jwt.api_jwt.decode_complete(auth_cookie, options={"verify_signature": False})
    assert auth_token["payload"]["permissions"] == {str(workspace.id): workspace_owner_permissions.value}

    # workspace can be listed
    response = await api_client.get("/api/workspaces/", cookies={SessionCookie: auth_cookie})
    workspace_json = response.json()[0]
    assert workspace_json.get("name") == user.email

    # workspace can be viewed by an owner
    response = await api_client.get(f"/api/workspaces/{workspace.id}", cookies={SessionCookie: auth_cookie})
    assert response.status_code == 200
    workspace_json = response.json()
    assert workspace_json.get("name") == user.email

    # domain event is sent
    assert len(domain_event_sender.events) == 3
    event = domain_event_sender.events[1]
    assert isinstance(event, UserRegistered)
    assert event.user_id == user.id
    assert event.email == user.email
    assert str(event.tenant_id) == workspace_json["id"]

    event1 = domain_event_sender.events[0]
    assert isinstance(event1, WorkspaceCreated)
    assert str(event1.workspace_id) == workspace_json["id"]

    # password can be reset only with providing a current one
    response = await api_client.patch(
        "/api/users/me", json={"password": "foobar@foo.com"}, cookies={SessionCookie: auth_cookie}
    )
    assert response.status_code == 400

    # password can be reset with providing a current one
    response = await api_client.patch(
        "/api/users/me",
        json={"password": "FooBar123456789123456789", "current_password": login_json["password"]},
        cookies={SessionCookie: auth_cookie},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_mfa_flow(
    api_client: AsyncClient,
    fast_api: FastAPI,
    domain_event_sender: InMemoryDomainEventPublisher,
    user_repository: UserRepository,
    password_helper: InsecureFastPasswordHelper,
    user_manager: UserManager,
    jwt_strategy: FixJWTStrategy,
    fix_deps: FixDependencies,
) -> None:
    verifier = fix_deps.service(SN.auth_email_sender, InMemoryVerifier)

    # register user
    registration_json = {"email": "user2@example.com", "password": "changeMe123456789"}
    response = await api_client.post("/api/auth/register", json=registration_json)
    assert response.status_code == 201

    # verify user
    user, token = verifier.verification_requests[0]
    response = await api_client.post("/api/auth/verify", json={"token": token})
    assert response.status_code == 200

    # login
    login_json = {"username": registration_json["email"], "password": registration_json["password"]}
    response = await api_client.post("/api/auth/jwt/login", data=login_json)
    assert response.status_code == 204
    auth_cookie = response.cookies.get(SessionCookie)
    assert auth_cookie is not None

    # mfa can be added and enabled
    response = await api_client.post("/api/auth/mfa/add", cookies={SessionCookie: auth_cookie})
    assert response.status_code == 200
    otp_config = OTPConfig.model_validate(response.json())
    totp = TOTP(otp_config.secret)
    response = await api_client.post(
        "/api/auth/mfa/enable", data={"otp": totp.now()}, cookies={SessionCookie: auth_cookie}
    )
    assert response.status_code == 204

    # login now requires mfa
    response = await api_client.post("/api/auth/jwt/login", data=login_json)
    assert response.status_code == 428

    # login with otp works
    response = await api_client.post("/api/auth/jwt/login", data=login_json | {"otp": totp.now()})
    assert response.status_code == 204

    # mfa can-not be disabled without valid otp
    response = await api_client.post(
        "/api/auth/mfa/disable", data={"otp": "wrong"}, cookies={SessionCookie: auth_cookie}
    )
    assert response.status_code == 428

    # mfa can be disabled with otp
    response = await api_client.post(
        "/api/auth/mfa/disable", data={"otp": totp.now()}, cookies={SessionCookie: auth_cookie}
    )
    assert response.status_code == 204

    # login without mfa works
    response = await api_client.post("/api/auth/jwt/login", data=login_json)
    assert response.status_code == 204

    # enable mfa again
    response = await api_client.post("/api/auth/mfa/add", cookies={SessionCookie: auth_cookie})
    assert response.status_code == 200
    otp_config = OTPConfig.model_validate(response.json())
    totp = TOTP(otp_config.secret)
    response = await api_client.post(
        "/api/auth/mfa/enable", data={"otp": totp.now()}, cookies={SessionCookie: auth_cookie}
    )
    assert response.status_code == 204

    # make sure only the new codes are stored
    async with user_repository.session_maker() as session:
        mfa_recovery_codes = (await session.execute(select(UserMFARecoveryCode))).scalars().all()
        assert len(mfa_recovery_codes) == 10

    # login now requires mfa
    response = await api_client.post("/api/auth/jwt/login", data=login_json)
    assert response.status_code == 428

    # login without otp but with recovery code works
    response = await api_client.post(
        "/api/auth/jwt/login", data=login_json | {"recovery_code": otp_config.recovery_codes[0]}
    )
    assert response.status_code == 204

    # login with the same code does not work
    response = await api_client.post(
        "/api/auth/jwt/login", data=login_json | {"recovery_code": otp_config.recovery_codes[0]}
    )
    assert response.status_code == 428

    # mfa can-not be disabled without valid recovery code
    response = await api_client.post(
        "/api/auth/mfa/disable", data={"recovery_code": "wrong"}, cookies={SessionCookie: auth_cookie}
    )
    assert response.status_code == 428

    # mfa can be disabled with recovery code
    response = await api_client.post(
        "/api/auth/mfa/disable",
        data={"recovery_code": otp_config.recovery_codes[1]},
        cookies={SessionCookie: auth_cookie},
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_auth_min_time(api_client: AsyncClient, fix_deps: FixDependencies, user_manager: UserManager) -> None:
    _, login_json, auth_cookie = await register_user(fix_deps, api_client)

    # API can be accessed
    resp = await api_client.get("/api/users/me", cookies={SessionCookie: auth_cookie})
    assert resp.status_code == 200

    # Update user's auth_min_time
    time.sleep(0.01)
    resp = await api_client.put(
        "/api/auth/jwt/expire", params=dict(expire_older_than=str(utc())), cookies={SessionCookie: auth_cookie}
    )
    assert resp.status_code == 204

    # API cannot be accessed, since JWT is invalid
    resp = await api_client.get("/api/users/me", cookies={SessionCookie: auth_cookie})
    assert resp.status_code == 401

    # Login again
    time.sleep(0.01)
    response = await api_client.post("/api/auth/jwt/login", data=login_json)
    assert response.status_code == 204
    auth_cookie = response.cookies.get(SessionCookie) or ""

    # API can be accessed
    resp = await api_client.get("/api/users/me", cookies={SessionCookie: auth_cookie})
    assert resp.status_code == 200
