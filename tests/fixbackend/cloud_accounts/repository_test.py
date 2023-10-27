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

from fixbackend.ids import FixCloudAccountId, ExternalId, CloudAccountId
from fixbackend.cloud_accounts.repository import CloudAccountRepositoryImpl
from fixbackend.types import AsyncSessionMaker
from fixbackend.cloud_accounts.models import CloudAccount, AwsCloudAccess
from fixbackend.workspaces.repository import WorkspaceRepository
from fixbackend.auth.models import User
from attrs import evolve


@pytest.mark.asyncio
async def test_create_cloud_account(
    async_session_maker: AsyncSessionMaker, workspace_repository: WorkspaceRepository, user: User
) -> None:
    cloud_account_repository = CloudAccountRepositoryImpl(session_maker=async_session_maker)
    org = await workspace_repository.create_workspace("foo", "foo", user)
    workspace_id = org.id
    account = CloudAccount(
        id=FixCloudAccountId(uuid.uuid4()),
        workspace_id=workspace_id,
        access=AwsCloudAccess(
            aws_account_id=CloudAccountId("123456789012"),
            role_name="foo",
            external_id=ExternalId(uuid.uuid4()),
        ),
        name="foo",
        is_configured=False,
        enabled=True,
    )

    # create
    created = await cloud_account_repository.create(cloud_account=account)
    assert created == account

    # get
    stored_account = await cloud_account_repository.get(id=account.id)
    assert account == stored_account

    # list
    accounts = await cloud_account_repository.list_by_workspace_id(workspace_id=workspace_id)
    assert len(accounts) == 1
    assert accounts[0] == account

    # update
    updated_account = evolve(
        account,
        access=AwsCloudAccess(
            aws_account_id=CloudAccountId("42"),
            role_name="bar",
            external_id=ExternalId(uuid.uuid4()),
        ),
    )
    updated = await cloud_account_repository.update(id=account.id, cloud_account=updated_account)
    stored_account = await cloud_account_repository.get(id=account.id)
    assert updated == stored_account == updated_account

    # delete
    await cloud_account_repository.delete(id=account.id)
    assert await cloud_account_repository.get(id=account.id) is None
