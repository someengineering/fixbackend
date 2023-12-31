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

from fixbackend.auth.user_repository import get_user_repository
from fixbackend.auth.models import User
from fixbackend.ids import WorkspaceId, UserId, SecurityTier
from fixbackend.workspaces.repository import WorkspaceRepository
from fixbackend.workspaces.models import Workspace
from fixbackend.subscription.models import AwsMarketplaceSubscription


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
async def test_create_workspace(workspace_repository: WorkspaceRepository, user: User) -> None:
    organization = await workspace_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )

    assert organization.name == "Test Organization"
    assert organization.slug == "test-organization"
    for owner in organization.owners:
        assert owner == user.id

    assert organization.security_tier == SecurityTier.Free

    assert len(organization.members) == 0

    # creating an organization with the same slug should raise an exception
    with pytest.raises(Exception):
        await workspace_repository.create_workspace(name="Test Organization", slug="test-organization", owner=user)


@pytest.mark.asyncio
async def test_get_workspace(workspace_repository: WorkspaceRepository, user: User) -> None:
    # we can get an existing organization by id
    organization = await workspace_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )

    retrieved_organization = await workspace_repository.get_workspace(organization.id)
    assert retrieved_organization == organization

    # if the organization does not exist, None should be returned
    retrieved_organization = await workspace_repository.get_workspace(WorkspaceId(uuid.uuid4()))
    assert retrieved_organization is None


@pytest.mark.asyncio
async def test_update_workspace(workspace_repository: WorkspaceRepository, user: User) -> None:
    # we can get an existing organization by id
    workspace = await workspace_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )

    await workspace_repository.update_workspace(workspace.id, "foobar", True)
    new_workspace = await workspace_repository.get_workspace(workspace.id)
    assert new_workspace is not None
    assert new_workspace.name == "foobar"
    assert new_workspace.external_id != workspace.external_id


@pytest.mark.asyncio
async def test_list_workspaces(workspace_repository: WorkspaceRepository, user: User, session: AsyncSession) -> None:
    workspace1 = await workspace_repository.create_workspace(
        name="Test Organization 1", slug="test-organization-1", owner=user
    )

    workspace2 = await workspace_repository.create_workspace(
        name="Test Organization 2", slug="test-organization-2", owner=user
    )

    user_db = await anext(get_user_repository(session))
    new_user_dict = {"email": "bar@bar.com", "hashed_password": "notreallyhashed", "is_verified": True}
    new_user = await user_db.create(new_user_dict)
    member_only_workspace = await workspace_repository.create_workspace(
        name="Test Organization 3", slug="test-organization-3", owner=new_user
    )
    await workspace_repository.add_to_workspace(workspace_id=member_only_workspace.id, user_id=user.id)

    # the user should be the owner of the organization
    workspaces = await workspace_repository.list_workspaces(user.id)
    assert len(workspaces) == 3
    assert set([o.id for o in workspaces]) == {workspace1.id, workspace2.id, member_only_workspace.id}


@pytest.mark.asyncio
async def test_add_to_workspace(workspace_repository: WorkspaceRepository, session: AsyncSession, user: User) -> None:
    # add an existing user to the organization
    organization = await workspace_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )
    org_id = organization.id

    user_db = await anext(get_user_repository(session))
    new_user_dict = {"email": "bar@bar.com", "hashed_password": "notreallyhashed", "is_verified": True}
    new_user = await user_db.create(new_user_dict)
    new_user_id = new_user.id
    await workspace_repository.add_to_workspace(workspace_id=org_id, user_id=new_user.id)

    retrieved_organization = await workspace_repository.get_workspace(org_id)
    assert retrieved_organization
    assert len(retrieved_organization.members) == 1
    assert retrieved_organization.members[0] == new_user.id

    assert retrieved_organization.owners[0] == user.id

    # when adding a user which is already a member of the organization, nothing should happen
    await workspace_repository.add_to_workspace(workspace_id=org_id, user_id=new_user_id)

    # when adding a non-existing user to the organization, an exception should be raised
    with pytest.raises(Exception):
        await workspace_repository.add_to_workspace(workspace_id=org_id, user_id=UserId(uuid.uuid4()))


@pytest.mark.asyncio
async def test_update_security_tier(
    workspace_repository: WorkspaceRepository,
    user: User,
    workspace: Workspace,
    subscription: AwsMarketplaceSubscription,
) -> None:
    current_tier = workspace.security_tier
    assert current_tier == SecurityTier.Free

    updated = await workspace_repository.update_security_tier(workspace.id, SecurityTier.HighSecurity)
    assert updated.security_tier == SecurityTier.HighSecurity

    # we can't update the security tier of an organization without a subscription
    without_subscription = await workspace_repository.create_workspace("not_subscribed", "not_subscribed", user)
    with pytest.raises(Exception):
        await workspace_repository.update_security_tier(without_subscription.id, SecurityTier.HighSecurity)
