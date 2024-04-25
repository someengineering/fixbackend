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


from attrs import evolve
from fixcloudutils.util import utc
import pytest

from fixbackend.auth.user_repository import get_user_repository
from fixbackend.auth.models import User
from fixbackend.permissions.models import Roles
from fixbackend.types import AsyncSessionMaker
from fixbackend.workspaces.invitation_repository import InvitationRepository
from fixbackend.workspaces.repository import WorkspaceRepository
from fixbackend.workspaces.models import Workspace


async def create_user(email: str, async_session_maker: AsyncSessionMaker) -> User:
    user_db = await anext(get_user_repository(async_session_maker))
    user_dict = {
        "email": email,
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    user = await user_db.create(user_dict)

    return user


@pytest.mark.asyncio
async def test_create_invitation(
    workspace_repository: WorkspaceRepository,
    invitation_repository: InvitationRepository,
    async_session_maker: AsyncSessionMaker,
    workspace: Workspace,
) -> None:
    user = await create_user("foo1@bar.com", async_session_maker)
    organization = await workspace_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )
    org_id = organization.id

    user2 = await create_user("123foo@bar.com", async_session_maker)

    invitation = await invitation_repository.create_invitation(
        workspace_id=org_id, email=user2.email, role=Roles.workspace_billing_admin
    )
    assert invitation.workspace_id == org_id
    assert invitation.email == user2.email
    assert invitation.role == Roles.workspace_billing_admin

    # create invitation is idempotent
    invitation2 = await invitation_repository.create_invitation(
        workspace_id=org_id, email=user2.email, role=Roles.workspace_billing_admin
    )
    assert invitation2 == invitation

    # can invite users to multiple workspaces
    invitation3 = await invitation_repository.create_invitation(
        workspace_id=workspace.id, email=user2.email, role=Roles.workspace_billing_admin
    )
    assert invitation3.workspace_id == workspace.id
    assert invitation3.email == user2.email

    external_email = "i_do_not_exist@bar.com"
    non_user_invitation = await invitation_repository.create_invitation(
        workspace_id=org_id, email=external_email, role=Roles.workspace_billing_admin
    )
    assert non_user_invitation.workspace_id == org_id
    assert non_user_invitation.email == external_email


@pytest.mark.asyncio
async def test_list_invitations(
    workspace_repository: WorkspaceRepository,
    invitation_repository: InvitationRepository,
    async_session_maker: AsyncSessionMaker,
) -> None:
    user = await create_user("foo@bar.com", async_session_maker)
    workspace = await workspace_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )

    user_db = await anext(get_user_repository(async_session_maker))
    user_dict = {
        "email": "bar@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    new_user = await user_db.create(user_dict)

    invitation = await invitation_repository.create_invitation(
        workspace_id=workspace.id, email=new_user.email, role=Roles.workspace_member
    )

    # list the invitations
    invitations = await invitation_repository.list_invitations(workspace_id=workspace.id)
    assert len(invitations) == 1
    assert invitations[0] == invitation


@pytest.mark.asyncio
async def test_get_invitation(
    workspace_repository: WorkspaceRepository,
    invitation_repository: InvitationRepository,
    async_session_maker: AsyncSessionMaker,
) -> None:
    user = await create_user("foo@bar.com", async_session_maker)
    workspace = await workspace_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )
    user_db = await anext(get_user_repository(async_session_maker))
    user_dict = {
        "email": "bar@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    new_user = await user_db.create(user_dict)

    invitation = await invitation_repository.create_invitation(
        workspace_id=workspace.id, email=new_user.email, role=Roles.workspace_member
    )

    stored_invitation = await invitation_repository.get_invitation(invitation_id=invitation.id)
    assert stored_invitation == invitation


@pytest.mark.asyncio
async def test_get_invitation_by_email(
    workspace_repository: WorkspaceRepository,
    invitation_repository: InvitationRepository,
    async_session_maker: AsyncSessionMaker,
) -> None:
    user = await create_user("foo@bar.com", async_session_maker)
    workspace = await workspace_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )
    user_db = await anext(get_user_repository(async_session_maker))
    user_dict = {
        "email": "bar@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    new_user = await user_db.create(user_dict)

    invitation = await invitation_repository.create_invitation(
        workspace_id=workspace.id, email=new_user.email, role=Roles.workspace_member
    )

    stored_invitation = await invitation_repository.get_invitation_by_email(email=new_user.email)
    assert stored_invitation == invitation


@pytest.mark.asyncio
async def test_update_invitation(
    workspace_repository: WorkspaceRepository,
    invitation_repository: InvitationRepository,
    async_session_maker: AsyncSessionMaker,
) -> None:
    user = await create_user("foo@bar.com", async_session_maker)
    workspace = await workspace_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )
    user_db = await anext(get_user_repository(async_session_maker))
    user_dict = {
        "email": "bar@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    new_user = await user_db.create(user_dict)

    invitation = await invitation_repository.create_invitation(
        workspace_id=workspace.id, email=new_user.email, role=Roles.workspace_member
    )
    assert invitation.accepted_at is None

    now = utc()

    updated = await invitation_repository.update_invitation(invitation.id, lambda i: evolve(i, accepted_at=now))
    assert updated.accepted_at is not None


@pytest.mark.asyncio
async def test_delete_invitation(
    workspace_repository: WorkspaceRepository,
    invitation_repository: InvitationRepository,
    async_session_maker: AsyncSessionMaker,
) -> None:
    user = await create_user("foo@bar.com", async_session_maker)
    organization = await workspace_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )
    org_id = organization.id

    user_db = await anext(get_user_repository(async_session_maker))
    user_dict = {
        "email": "bar@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    new_user = await user_db.create(user_dict)

    invitation = await invitation_repository.create_invitation(
        workspace_id=org_id, email=new_user.email, role=Roles.workspace_member
    )

    # delete the invitation
    await invitation_repository.delete_invitation(invitation_id=invitation.id)

    # the invitation should not exist anymore
    invitations = await invitation_repository.list_invitations(workspace_id=org_id)
    assert len(invitations) == 0
