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

import datetime
import uuid
from attr import evolve

import pytest
from sqlalchemy import select

from fixbackend.auth.user_repository import get_user_repository
from fixbackend.auth.models import User
from fixbackend.ids import WorkspaceId, UserId, ProductTier
from fixbackend.permissions.models import Roles, UserRole
from fixbackend.workspaces.repository import WorkspaceRepository
from fixbackend.permissions.role_repository import RoleRepository
from fixbackend.workspaces.models import Workspace, orm
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.types import AsyncSessionMaker
from fixcloudutils.util import utc


@pytest.fixture
async def user(async_session_maker: AsyncSessionMaker) -> User:
    user_db = await anext(get_user_repository(async_session_maker))
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
    assert organization.owner_id == user.id

    assert organization.current_product_tier() == ProductTier.Trial
    assert organization.selected_product_tier == ProductTier.Trial

    assert len(organization.members) == 1
    for member in organization.members:
        assert member == user.id

    # creating an organization with the same slug should not raise an exception but adjust the slug
    same_slug = await workspace_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )
    assert same_slug.slug == f"test-organization-{same_slug.id}"


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
async def test_list_workspaces(
    workspace_repository: WorkspaceRepository, user: User, async_session_maker: AsyncSessionMaker
) -> None:
    workspace1 = await workspace_repository.create_workspace(
        name="Test Organization 1", slug="test-organization-1", owner=user
    )

    workspace2 = await workspace_repository.create_workspace(
        name="Test Organization 2", slug="test-organization-2", owner=user
    )

    user_db = await anext(get_user_repository(async_session_maker))
    new_user_dict = {"email": "bar@bar.com", "hashed_password": "notreallyhashed", "is_verified": True}
    new_user = await user_db.create(new_user_dict)
    member_only_workspace = await workspace_repository.create_workspace(
        name="Test Organization 3", slug="test-organization-3", owner=new_user
    )
    await workspace_repository.add_to_workspace(
        workspace_id=member_only_workspace.id, user_id=user.id, role=Roles.workspace_member
    )

    # the user should be the owner of the organization
    workspaces = await workspace_repository.list_workspaces(user)
    assert len(workspaces) == 3
    assert set([o.id for o in workspaces]) == {workspace1.id, workspace2.id, member_only_workspace.id}

    owner_of_ws1 = evolve(
        user, roles=[UserRole(user_id=user.id, workspace_id=workspace1.id, role_names=Roles.workspace_billing_admin)]
    )
    assignable_workspaces = await workspace_repository.list_workspaces(owner_of_ws1, can_assign_subscriptions=True)
    assert len(assignable_workspaces) == 1
    assert assignable_workspaces[0].id == workspace1.id


@pytest.mark.asyncio
async def test_add_to_workspace(
    workspace_repository: WorkspaceRepository,
    async_session_maker: AsyncSessionMaker,
    user: User,
    role_repository: RoleRepository,
) -> None:
    # add an existing user to the organization
    organization = await workspace_repository.create_workspace(
        name="Test Organization", slug="test-organization", owner=user
    )
    org_id = organization.id

    user_db = await anext(get_user_repository(async_session_maker))
    new_user_dict = {"email": "bar@bar.com", "hashed_password": "notreallyhashed", "is_verified": True}
    new_user = await user_db.create(new_user_dict)
    new_user_id = new_user.id
    await workspace_repository.add_to_workspace(
        workspace_id=org_id, user_id=new_user.id, role=Roles.workspace_billing_admin
    )

    retrieved_organization = await workspace_repository.get_workspace(org_id)
    assert retrieved_organization
    assert len(retrieved_organization.members) == 2
    assert new_user_id in retrieved_organization.members

    assert retrieved_organization.owner_id == user.id
    assert user.id in retrieved_organization.members

    # role should be added to the user
    roles = await role_repository.list_roles(new_user_id)
    assert len(roles) == 1
    assert roles[0].user_id == new_user_id
    assert roles[0].workspace_id == org_id
    assert roles[0].role_names == Roles.workspace_billing_admin

    # when adding a user which is already a member of the organization, nothing should happen
    await workspace_repository.add_to_workspace(
        workspace_id=org_id, user_id=new_user_id, role=Roles.workspace_billing_admin
    )

    # when adding a non-existing user to the organization, an exception should be raised
    with pytest.raises(Exception):
        await workspace_repository.add_to_workspace(
            workspace_id=org_id, user_id=UserId(uuid.uuid4()), role=Roles.workspace_billing_admin
        )


@pytest.mark.asyncio
async def test_update_product_tier(
    workspace_repository: WorkspaceRepository,
    user: User,
    workspace: Workspace,
    aws_marketplace_subscription: AwsMarketplaceSubscription,
) -> None:
    billing_admin = evolve(
        user, roles=[UserRole(user_id=user.id, workspace_id=workspace.id, role_names=Roles.workspace_billing_admin)]
    )

    await workspace_repository.update_subscription(workspace.id, aws_marketplace_subscription.id)

    current_tier = workspace.current_product_tier()
    assert current_tier == ProductTier.Trial
    assert workspace.selected_product_tier == ProductTier.Trial
    assert workspace.highest_current_cycle_tier is None

    updated = await workspace_repository.update_product_tier(workspace.id, ProductTier.Enterprise)
    assert updated.current_product_tier() == ProductTier.Enterprise
    assert updated.selected_product_tier == ProductTier.Enterprise
    assert updated.highest_current_cycle_tier == ProductTier.Enterprise
    active_tier_ends_at = updated.current_cycle_ends_at
    assert active_tier_ends_at is not None

    assert await workspace_repository.get_product_tier(workspace.id) == ProductTier.Enterprise

    # when downgrading the tier, we should keep the tier till the end of the billing cycle
    updated = await workspace_repository.update_product_tier(workspace.id, ProductTier.Plus)
    assert updated.current_product_tier() == ProductTier.Enterprise
    assert updated.selected_product_tier == ProductTier.Plus
    assert updated.highest_current_cycle_tier == ProductTier.Enterprise
    assert updated.current_cycle_ends_at == active_tier_ends_at

    # we can't update the security tier of an organization without a subscription
    without_subscription = await workspace_repository.create_workspace(
        "not_subscribed", "not_subscribed", billing_admin
    )
    with pytest.raises(Exception):
        await workspace_repository.update_product_tier(without_subscription.id, ProductTier.Enterprise)


@pytest.mark.asyncio
async def test_assign_subscription(
    workspace_repository: WorkspaceRepository,
    workspace: Workspace,
    aws_marketplace_subscription: AwsMarketplaceSubscription,
) -> None:
    assert workspace.subscription_id is None

    workspace = await workspace_repository.update_subscription(workspace.id, aws_marketplace_subscription.id)
    assert workspace.subscription_id == aws_marketplace_subscription.id

    with_subscription = await workspace_repository.list_workspaces_by_subscription_id(aws_marketplace_subscription.id)
    assert len(with_subscription) == 1
    assert with_subscription[0].id == workspace.id


@pytest.mark.asyncio
async def test_on_hold(
    workspace_repository: WorkspaceRepository,
    workspace: Workspace,
) -> None:
    assert workspace.payment_on_hold_since is None

    yesterday = utc().replace(microsecond=0) - datetime.timedelta(days=1)
    before_yesterday = yesterday - datetime.timedelta(days=1)

    assert await workspace_repository.list_by_on_hold(before=yesterday) == []

    workspace = await workspace_repository.update_payment_on_hold(workspace.id, yesterday)

    assert workspace.payment_on_hold_since == yesterday

    assert await workspace_repository.list_by_on_hold(before=utc()) == [workspace]

    assert await workspace_repository.list_by_on_hold(before=before_yesterday) == []


@pytest.mark.asyncio
async def test_expired_trials(
    workspace_repository: WorkspaceRepository,
    workspace: Workspace,
    async_session_maker: AsyncSessionMaker,
) -> None:

    async with async_session_maker() as session:
        statement = select(orm.Organization).where(orm.Organization.id == workspace.id)
        results = await session.execute(statement)
        org = results.unique().scalar_one_or_none()
        assert org
        org.created_at = utc() - datetime.timedelta(days=1)
        await session.commit()
        await session.refresh(org)
        workspace = org.to_model()

    assert await workspace_repository.list_expired_trials(been_in_trial_tier_for=datetime.timedelta(days=14)) == []

    assert await workspace_repository.list_expired_trials(been_in_trial_tier_for=datetime.timedelta(seconds=0)) == [
        workspace
    ]
