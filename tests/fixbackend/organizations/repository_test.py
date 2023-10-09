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

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.auth.db import get_user_repository
from fixbackend.auth.models import User
from fixbackend.ids import WorkspaceId, UserId
from fixbackend.workspaces.repository import WorkspaceRepository


@pytest.fixture
async def user(session: AsyncSession) -> User:
    user_db = await anext(get_user_repository(session))
    user_dict = {
        "email": "foo@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    user = await user_db.create(user_dict)

    return user


@pytest.mark.asyncio
async def test_create_organization(organization_repository: WorkspaceRepository, user: User) -> None:
    organization = await organization_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )

    assert organization.name == "Test Organization"
    assert organization.slug == "test-organization"
    for owner in organization.owners:
        assert owner == user.id

    assert len(organization.members) == 0

    # creating an organization with the same slug should raise an exception
    with pytest.raises(Exception):
        await organization_repository.create_workspace(name="Test Organization", slug="test-organization", owner=user)


@pytest.mark.asyncio
async def test_get_organization(organization_repository: WorkspaceRepository, user: User) -> None:
    # we can get an existing organization by id
    organization = await organization_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )

    retrieved_organization = await organization_repository.get_workspace(organization.id)
    assert retrieved_organization == organization

    # if the organization does not exist, None should be returned
    retrieved_organization = await organization_repository.get_workspace(WorkspaceId(uuid.uuid4()))
    assert retrieved_organization is None


@pytest.mark.asyncio
async def test_list_organizations(organization_repository: WorkspaceRepository, user: User) -> None:
    organization1 = await organization_repository.create_workspace(
        name="Test Organization 1", slug="test-organization-1", owner=user
    )

    organization2 = await organization_repository.create_workspace(
        name="Test Organization 2", slug="test-organization-2", owner=user
    )

    # the user should be the owner of the organization
    organizations = await organization_repository.list_workspaces(user.id)
    assert len(organizations) == 2
    assert set([o.id for o in organizations]) == {organization1.id, organization2.id}


@pytest.mark.asyncio
async def test_add_to_organization(
    organization_repository: WorkspaceRepository, session: AsyncSession, user: User
) -> None:
    # add an existing user to the organization
    organization = await organization_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )
    org_id = organization.id

    user_db = await anext(get_user_repository(session))
    new_user_dict = {"email": "bar@bar.com", "hashed_password": "notreallyhashed", "is_verified": True}
    new_user = await user_db.create(new_user_dict)
    new_user_id = new_user.id
    await organization_repository.add_to_workspace(workspace_id=org_id, user_id=new_user.id)

    retrieved_organization = await organization_repository.get_workspace(org_id)
    assert retrieved_organization
    assert len(retrieved_organization.members) == 1
    assert retrieved_organization.members[0] == new_user.id

    # when adding a user which is already a member of the organization, nothing should happen
    await organization_repository.add_to_workspace(workspace_id=org_id, user_id=new_user_id)

    # when adding a non-existing user to the organization, an exception should be raised
    with pytest.raises(Exception):
        await organization_repository.add_to_workspace(workspace_id=org_id, user_id=UserId(uuid.uuid4()))


@pytest.mark.asyncio
async def test_create_invitation(
    organization_repository: WorkspaceRepository, session: AsyncSession, user: User
) -> None:
    organization = await organization_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )
    org_id = organization.id

    user_db = await anext(get_user_repository(session))
    user_dict = {
        "email": "123foo@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    new_user = await user_db.create(user_dict)
    new_user_id = new_user.id

    invitation = await organization_repository.create_invitation(workspace_id=org_id, user_id=new_user.id)
    assert invitation.workspace_id == org_id
    assert invitation.user_id == new_user_id


@pytest.mark.asyncio
async def test_accept_invitation(
    organization_repository: WorkspaceRepository, session: AsyncSession, user: User
) -> None:
    organization = await organization_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )
    org_id = organization.id

    user_db = await anext(get_user_repository(session))
    user_dict = {
        "email": "123foo@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    new_user = await user_db.create(user_dict)

    invitation = await organization_repository.create_invitation(workspace_id=org_id, user_id=new_user.id)

    # accept the invitation
    await organization_repository.accept_invitation(invitation_id=invitation.id)

    retrieved_organization = await organization_repository.get_workspace(org_id)
    assert retrieved_organization
    assert len(retrieved_organization.members) == 1
    assert retrieved_organization.members[0] == new_user.id


@pytest.mark.asyncio
async def test_list_invitations(
    organization_repository: WorkspaceRepository, session: AsyncSession, user: User
) -> None:
    organization = await organization_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )
    org_id = organization.id

    user_db = await anext(get_user_repository(session))
    user_dict = {
        "email": "bar@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    new_user = await user_db.create(user_dict)

    invitation = await organization_repository.create_invitation(workspace_id=org_id, user_id=new_user.id)

    # list the invitations
    invitations = await organization_repository.list_invitations(workspace_id=org_id)
    assert len(invitations) == 1
    assert invitations[0] == invitation


@pytest.mark.asyncio
async def test_delete_invitation(
    organization_repository: WorkspaceRepository, session: AsyncSession, user: User
) -> None:
    organization = await organization_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )
    org_id = organization.id

    user_db = await anext(get_user_repository(session))
    user_dict = {
        "email": "bar@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    new_user = await user_db.create(user_dict)

    invitation = await organization_repository.create_invitation(workspace_id=org_id, user_id=new_user.id)

    # delete the invitation
    await organization_repository.delete_invitation(invitation_id=invitation.id)

    # the invitation should not exist anymore
    invitations = await organization_repository.list_invitations(workspace_id=org_id)
    assert len(invitations) == 0
