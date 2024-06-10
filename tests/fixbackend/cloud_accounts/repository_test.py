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
from fixbackend.cloud_accounts.models import (
    AwsCloudAccess,
    AzureCloudAccess,
    CloudAccount,
    CloudAccountState,
    CloudAccountStates,
    GcpCloudAccess,
)
from fixbackend.cloud_accounts.repository import CloudAccountRepositoryImpl
from fixbackend.ids import (
    AwsRoleName,
    AzureSubscriptionCredentialsId,
    CloudAccountAlias,
    CloudAccountId,
    CloudAccountName,
    CloudNames,
    ExternalId,
    FixCloudAccountId,
    GcpServiceAccountKeyId,
    UserCloudAccountName,
)
from fixbackend.types import AsyncSessionMaker
from fixbackend.workspaces.repository import WorkspaceRepository
from fixbackend.dispatcher.next_run_repository import NextRunRepository


@pytest.mark.asyncio
async def test_create_aws_cloud_account(
    async_session_maker: AsyncSessionMaker,
    workspace_repository: WorkspaceRepository,
    user: User,
    next_run_repository: NextRunRepository,
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
        CloudAccountStates.Discovered(cloud_access, enabled=True),
        CloudAccountStates.Discovered(cloud_access, enabled=False),
        CloudAccountStates.Configured(cloud_access, enabled=True, scan=True),
        CloudAccountStates.Configured(cloud_access, enabled=True, scan=True),
        CloudAccountStates.Degraded(cloud_access, error="test error"),
        CloudAccountStates.Deleted(),
    ]

    configured_account_id: FixCloudAccountId | None = None

    configured_count = 0

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
            failed_scan_count=configured_count * 42,  # only the last one has failed scans
            last_task_id=None,
        )

        if isinstance(account_state, CloudAccountStates.Configured):
            configured_count += 1

        if isinstance(account_state, CloudAccountStates.Configured):
            configured_account_id = account.id

        # create
        created = await cloud_account_repository.create(cloud_account=account)
        assert created == account

        # get
        stored_account = await cloud_account_repository.get(id=account.id)
        assert account == stored_account

    assert configured_account_id is not None

    # get by account_id
    account_by_id = await cloud_account_repository.get_by_account_id(
        workspace_id=workspace_id, account_id=CloudAccountId("1")
    )
    assert account_by_id is not None

    # list
    accounts = await cloud_account_repository.list_by_workspace_id(workspace_id=workspace_id)
    assert len(accounts) == len(account_states)
    collectable_accounts = await cloud_account_repository.list_by_workspace_id(
        workspace_id=workspace_id, ready_for_collection=True
    )
    assert len(collectable_accounts) == 2

    new_cloud_access = AwsCloudAccess(
        role_name=AwsRoleName("bar"),
        external_id=ExternalId(uuid.uuid4()),
    )

    # list_by_id
    accounts = await cloud_account_repository.list(ids=[configured_account_id])
    assert len(accounts) == 1

    # list all discovered
    discovered_accounts = await cloud_account_repository.list_all_discovered_accounts()
    assert len(discovered_accounts) == 2
    for acc in discovered_accounts:
        assert acc.state.state_name == CloudAccountStates.Discovered.state_name

    # list where we have failed scans
    # we set the next tenant run 2 days in the future so the join in the query below should work fine
    await next_run_repository.create(workspace_id, utc() + timedelta(days=1))
    failed_scan_accounts = await cloud_account_repository.list_non_hourly_failed_scans_accounts(now=utc())
    assert len(failed_scan_accounts) == 1
    assert failed_scan_accounts[0].state.state_name == CloudAccountStates.Configured.state_name
    assert failed_scan_accounts[0].failed_scan_count == 42
    assert failed_scan_accounts[0].account_id == CloudAccountId("4")  # the fifth account created in the loop above
    # if next scan is less than 2 hours from now, it should not be included in the list
    await next_run_repository.update_next_run_at(workspace_id, utc() + timedelta(hours=1))
    assert await cloud_account_repository.list_non_hourly_failed_scans_accounts(now=utc()) == []

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


@pytest.mark.asyncio
async def test_create_gcp_cloud_account(
    async_session_maker: AsyncSessionMaker,
    workspace_repository: WorkspaceRepository,
    user: User,
) -> None:
    cloud_account_repository = CloudAccountRepositoryImpl(session_maker=async_session_maker)
    org = await workspace_repository.create_workspace("foo", "foo", user)
    workspace_id = org.id

    cloud_access = GcpCloudAccess(
        service_account_key_id=GcpServiceAccountKeyId(uuid.uuid4()),
    )

    account = CloudAccount(
        id=FixCloudAccountId(uuid.uuid4()),
        account_id=CloudAccountId("gcp-123"),
        workspace_id=workspace_id,
        cloud=CloudNames.GCP,
        state=CloudAccountStates.Configured(cloud_access, enabled=True, scan=True),
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
        failed_scan_count=0,  # only the last one has failed scans
        last_task_id=None,
    )

    # create
    created = await cloud_account_repository.create(cloud_account=account)
    assert created == account

    # get
    stored_account = await cloud_account_repository.get(id=account.id)
    assert account == stored_account

    # get by account_id
    account_by_id = await cloud_account_repository.get_by_account_id(
        workspace_id=workspace_id, account_id=CloudAccountId("gcp-123")
    )
    assert account_by_id is not None


@pytest.mark.asyncio
async def test_create_azure_cloud_account(
    async_session_maker: AsyncSessionMaker,
    workspace_repository: WorkspaceRepository,
    user: User,
) -> None:
    cloud_account_repository = CloudAccountRepositoryImpl(session_maker=async_session_maker)
    org = await workspace_repository.create_workspace("foo", "foo", user)
    workspace_id = org.id

    cloud_access = AzureCloudAccess(
        subscription_credentials_id=AzureSubscriptionCredentialsId(uuid.uuid4()),
    )

    account = CloudAccount(
        id=FixCloudAccountId(uuid.uuid4()),
        account_id=CloudAccountId("azure-123"),
        workspace_id=workspace_id,
        cloud=CloudNames.Azure,
        state=CloudAccountStates.Configured(cloud_access, enabled=True, scan=True),
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
        failed_scan_count=0,  # only the last one has failed scans
        last_task_id=None,
    )

    # create
    created = await cloud_account_repository.create(cloud_account=account)
    assert created == account

    # get
    stored_account = await cloud_account_repository.get(id=account.id)
    assert account == stored_account

    # get by account_id
    account_by_id = await cloud_account_repository.get_by_account_id(
        workspace_id=workspace_id, account_id=CloudAccountId("azure-123")
    )
    assert account_by_id is not None
