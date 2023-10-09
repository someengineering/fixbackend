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
from typing import Dict, List, Optional, Tuple

import pytest

from fixbackend.cloud_accounts.models import CloudAccount, AwsCloudAccess
from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.cloud_accounts.service import CloudAccountServiceImpl
from fixbackend.ids import CloudAccountId, ExternalId, WorkspaceId
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepositoryImpl
from fixcloudutils.redis.event_stream import RedisStreamPublisher
from fixcloudutils.redis.pub_sub import RedisPubSubPublisher
from fixcloudutils.types import Json


class CloudAccountRepositoryMock(CloudAccountRepository):
    def __init__(self) -> None:
        self.accounts: Dict[CloudAccountId, CloudAccount] = {}

    async def create(self, cloud_account: CloudAccount) -> CloudAccount:
        self.accounts[cloud_account.id] = cloud_account
        return cloud_account

    async def get(self, id: CloudAccountId) -> CloudAccount | None:
        return self.accounts.get(id)

    async def list_by_workspace_id(self, workspace_id: WorkspaceId) -> List[CloudAccount]:
        return [account for account in self.accounts.values() if account.workspace_id == workspace_id]

    async def delete(self, id: CloudAccountId) -> None:
        self.accounts.pop(id)


test_workspace_id = WorkspaceId(uuid.uuid4())

account_id = "foobar"
role_name = "FooBarRole"
external_id = ExternalId(uuid.uuid4())

organization = Workspace(
    id=test_workspace_id,
    name="Test Organization",
    slug="test-organization",
    external_id=external_id,
    owners=[],
    members=[],
)


class OrganizationServiceMock(WorkspaceRepositoryImpl):
    def __init__(self) -> None:
        pass

    async def get_workspace(self, workspace_id: WorkspaceId, with_users: bool = False) -> Workspace | None:
        if workspace_id != test_workspace_id:
            return None
        return organization


class RedisStreamPublisherMock(RedisStreamPublisher):
    def __init__(self) -> None:
        self.last_message: Optional[Tuple[str, Json]] = None

    async def publish(self, kind: str, message: Json) -> None:
        self.last_message = (kind, message)


class RedisPubSubPublisherMock(RedisPubSubPublisher):
    def __init__(self) -> None:
        self.last_message: Optional[Tuple[str, Json, Optional[str]]] = None

    async def publish(self, kind: str, message: Json, channel: Optional[str] = None) -> None:
        self.last_message = (kind, message, channel)


@pytest.mark.asyncio
async def test_create_aws_account() -> None:
    repository = CloudAccountRepositoryMock()
    organization_repository = OrganizationServiceMock()
    stream_publisher = RedisStreamPublisherMock()
    pubsub_publisher = RedisPubSubPublisherMock()
    service = CloudAccountServiceImpl(organization_repository, repository, stream_publisher, pubsub_publisher)

    # happy case
    acc = await service.create_aws_account(test_workspace_id, account_id, role_name, external_id)
    assert len(repository.accounts) == 1
    account = repository.accounts.get(acc.id)
    assert account is not None
    assert account.workspace_id == test_workspace_id
    assert isinstance(account.access, AwsCloudAccess)
    assert account.access.account_id == account_id
    assert account.access.role_name == role_name
    assert account.access.external_id == external_id

    message = {
        "cloud_account_id": str(account.id),
        "workspace_id": str(account.workspace_id),
        "aws_account_id": account_id,
    }

    assert stream_publisher.last_message is not None
    assert stream_publisher.last_message[0] == "cloud_account_created"
    assert stream_publisher.last_message[1] == message

    assert pubsub_publisher.last_message is not None
    assert pubsub_publisher.last_message[0] == "cloud_account_created"
    assert pubsub_publisher.last_message[1] == message
    assert pubsub_publisher.last_message[2] == f"tenant-events::{test_workspace_id}"

    # account already exists
    with pytest.raises(Exception):
        await service.create_aws_account(test_workspace_id, account_id, role_name, external_id)

    # wrong external id
    with pytest.raises(Exception):
        await service.create_aws_account(test_workspace_id, account_id, role_name, ExternalId(uuid.uuid4()))

    # wrong tenant id
    with pytest.raises(Exception):
        await service.create_aws_account(WorkspaceId(uuid.uuid4()), account_id, role_name, external_id)


@pytest.mark.asyncio
async def test_delete_aws_account() -> None:
    repository = CloudAccountRepositoryMock()
    organization_repository = OrganizationServiceMock()
    stream_publisher = RedisStreamPublisherMock()
    pubsub_publisher = RedisPubSubPublisherMock()
    service = CloudAccountServiceImpl(organization_repository, repository, stream_publisher, pubsub_publisher)

    account = await service.create_aws_account(test_workspace_id, account_id, role_name, external_id)
    assert len(repository.accounts) == 1

    # deleting someone's else account
    with pytest.raises(Exception):
        await service.delete_cloud_account(account.id, WorkspaceId(uuid.uuid4()))
    assert len(repository.accounts) == 1

    # success
    await service.delete_cloud_account(account.id, test_workspace_id)
    assert len(repository.accounts) == 0

    assert stream_publisher.last_message is not None
    assert stream_publisher.last_message[0] == "cloud_account_deleted"
    assert stream_publisher.last_message[1] == {"id": str(account.id)}
