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
from typing import List

from fixbackend.ids import (
    FixCloudAccountId,
    ExternalId,
    CloudAccountId,
    AwsRoleName,
    CloudNames,
    CloudAccountName,
    CloudAccountAlias,
    UserCloudAccountName,
)
from fixbackend.cloud_accounts.repository import CloudAccountRepositoryImpl
from fixbackend.types import AsyncSessionMaker
from fixbackend.cloud_accounts.models import CloudAccount, AwsCloudAccess, CloudAccountState, CloudAccountStates
from fixbackend.workspaces.repository import WorkspaceRepository
from fixbackend.auth.models import User
from attrs import evolve


@pytest.mark.asyncio
async def test_create_cloud_account(
    async_session_maker: AsyncSessionMaker, workspace_repository: WorkspaceRepository, user: User
) -> None:
    cloud_account_repository = CloudAccountRepositoryImpl(session_maker=async_session_maker)
    org = await workspace_repository.create_workspace("foo", "foo", user)
    foobar_org = await workspace_repository.create_workspace("foobar", "foobar", user)
    workspace_id = org.id

    cloud_access = AwsCloudAccess(
        role_name=AwsRoleName("foo"),
        external_id=ExternalId(uuid.uuid4()),
    )

    account_states: List[CloudAccountState] = [
        CloudAccountStates.Detected(),
        CloudAccountStates.Discovered(cloud_access),
        CloudAccountStates.Configured(cloud_access, enabled=True),
        CloudAccountStates.Degraded(cloud_access, error="test error"),
    ]

    configured_account_id: FixCloudAccountId | None = None

    # only to test the number of accounts
    await cloud_account_repository.create(
        CloudAccount(
            id=FixCloudAccountId(uuid.uuid4()),
            account_id=CloudAccountId("foobar"),
            workspace_id=foobar_org.id,
            cloud=CloudNames.AWS,
            state=account_states[1],
            account_name=CloudAccountName("foo"),
            account_alias=CloudAccountAlias("foo_alias"),
            user_account_name=UserCloudAccountName("foo_user_provided_name"),
            privileged=False,
        )
    )

    for idx, account_state in enumerate(account_states):
        account = CloudAccount(
            id=FixCloudAccountId(uuid.uuid4()),
            account_id=CloudAccountId(str(idx)),
            workspace_id=workspace_id,
            cloud=CloudNames.AWS,
            state=account_state,
            account_name=CloudAccountName("foo"),
            account_alias=CloudAccountAlias("foo_alias"),
            user_account_name=UserCloudAccountName("foo_user_provided_name"),
            privileged=False,
        )

        if isinstance(account_state, CloudAccountStates.Configured):
            configured_account_id = account.id

        # create
        created = await cloud_account_repository.create(cloud_account=account)
        assert created == account

        # get
        stored_account = await cloud_account_repository.get(id=account.id)
        assert account == stored_account

    assert configured_account_id is not None

    # list
    accounts = await cloud_account_repository.list_by_workspace_id(workspace_id=workspace_id)
    assert len(accounts) == len(account_states)
    collectable_accounts = await cloud_account_repository.list_by_workspace_id(
        workspace_id=workspace_id, ready_for_collection=True
    )
    assert len(collectable_accounts) == 1

    new_cloud_access = AwsCloudAccess(
        role_name=AwsRoleName("bar"),
        external_id=ExternalId(uuid.uuid4()),
    )

    # update
    def update_account(account: CloudAccount) -> CloudAccount:
        match account.state:
            case CloudAccountStates.Configured(AwsCloudAccess(_, _), _):
                return evolve(account, state=evolve(account.state, access=new_cloud_access))

            case _:
                raise ValueError("Invalid state")

    updated = await cloud_account_repository.update(id=configured_account_id, update_fn=update_account)
    stored_account = await cloud_account_repository.get(id=configured_account_id)
    assert updated == stored_account
    match updated.state:
        case CloudAccountStates.Configured(AwsCloudAccess(exteral_id, role_name), True):
            assert exteral_id == new_cloud_access.external_id
            assert role_name == new_cloud_access.role_name
        case _:
            raise ValueError("Invalid state")

    # count accounts
    assert await cloud_account_repository.number_of_accounts(workspace_id=workspace_id) == len(account_states)
    assert await cloud_account_repository.number_of_accounts(workspace_id=foobar_org.id) == 1

    # delete
    await cloud_account_repository.delete(id=configured_account_id)
    assert await cloud_account_repository.get(id=configured_account_id) is None
