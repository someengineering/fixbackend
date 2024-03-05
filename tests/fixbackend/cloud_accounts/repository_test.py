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
from datetime import timedelta
from typing import List

import pytest
from attrs import evolve
from fixcloudutils.util import utc

from fixbackend.auth.models import User
from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount, CloudAccountState, CloudAccountStates
from fixbackend.cloud_accounts.repository import CloudAccountRepositoryImpl
from fixbackend.ids import (
    AwsRoleName,
    CloudAccountAlias,
    CloudAccountId,
    CloudAccountName,
    CloudNames,
    ExternalId,
    FixCloudAccountId,
    UserCloudAccountName,
)
from fixbackend.types import AsyncSessionMaker
from fixbackend.workspaces.repository import WorkspaceRepository


@pytest.mark.asyncio
async def test_create_cloud_account(
    async_session_maker: AsyncSessionMaker, workspace_repository: WorkspaceRepository, user: User
) -> None:
    cloud_account_repository = CloudAccountRepositoryImpl(session_maker=async_session_maker)
    org = await workspace_repository.create_workspace("foo", "foo", user)
    workspace_id = org.id

    cloud_access = AwsCloudAccess(
        role_name=AwsRoleName("foo"),
        external_id=ExternalId(uuid.uuid4()),
    )

    account_states: List[CloudAccountState] = [
        CloudAccountStates.Detected(),
        CloudAccountStates.Discovered(cloud_access),
        CloudAccountStates.Configured(cloud_access, enabled=True, scan=True),
        CloudAccountStates.Degraded(cloud_access, error="test error"),
        CloudAccountStates.Deleted(),
    ]

    configured_account_id: FixCloudAccountId | None = None

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
            last_scan_started_at=None,
            last_scan_duration_seconds=0,
            last_scan_resources_scanned=0,
            next_scan=None,
            created_at=utc().replace(microsecond=0),
            updated_at=utc().replace(microsecond=0),
            state_updated_at=utc().replace(microsecond=0),
            cf_stack_version=0,
            failed_scan_count=0,
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

    # list_by_id
    accounts = await cloud_account_repository.list(ids=[configured_account_id])
    assert len(accounts) == 1

    # list all discovered
    discovered_accounts = await cloud_account_repository.list_all_discovered_accounts()
    assert len(discovered_accounts) == 1
    assert discovered_accounts[0].state.state_name == CloudAccountStates.Discovered.state_name

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

    # update 2
    timestamp = utc().replace(microsecond=0)
    await cloud_account_repository.update(
        configured_account_id,
        lambda acc: evolve(
            acc,
            last_scan_duration_seconds=123,
            last_scan_resources_scanned=456,
            last_scan_started_at=timestamp,
            next_scan=timestamp + timedelta(hours=1),
        ),
    )
    with_last_scan = await cloud_account_repository.get(id=configured_account_id)
    assert with_last_scan
    assert with_last_scan.last_scan_duration_seconds == 123
    assert with_last_scan.last_scan_resources_scanned == 456
    assert with_last_scan.last_scan_started_at == timestamp
    assert with_last_scan.next_scan == (timestamp + timedelta(hours=1))

    # delete
    await cloud_account_repository.delete(id=configured_account_id)
    assert await cloud_account_repository.get(id=configured_account_id) is None
