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
from fixcloudutils.redis.event_stream import RedisStreamPublisher
from fixcloudutils.redis.pub_sub import RedisPubSubPublisher
from fixcloudutils.types import Json
from redis.asyncio import Redis

from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount, LastScanInfo
from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.cloud_accounts.service_impl import CloudAccountServiceImpl
from fixbackend.domain_events.events import AwsAccountDiscovered, Event
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.ids import FixCloudAccountId, ExternalId, WorkspaceId, CloudAccountId
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepositoryImpl
from fixbackend.domain_events.events import TenantAccountsCollected, CloudAccountCollectInfo
from datetime import datetime
from fixcloudutils.redis.event_stream import MessageContext
from fixbackend.cloud_accounts.last_scan_repository import LastScanRepository


class CloudAccountRepositoryMock(CloudAccountRepository):
    def __init__(self) -> None:
        self.accounts: Dict[FixCloudAccountId, CloudAccount] = {}

    async def create(self, cloud_account: CloudAccount) -> CloudAccount:
        self.accounts[cloud_account.id] = cloud_account
        return cloud_account

    async def get(self, id: FixCloudAccountId) -> CloudAccount | None:
        return self.accounts.get(id)

    async def update(self, id: FixCloudAccountId, cloud_account: CloudAccount) -> CloudAccount:
        self.accounts[id] = cloud_account
        return cloud_account

    async def list_by_workspace_id(self, workspace_id: WorkspaceId) -> List[CloudAccount]:
        return [account for account in self.accounts.values() if account.workspace_id == workspace_id]

    async def delete(self, id: FixCloudAccountId) -> None:
        self.accounts.pop(id)


test_workspace_id = WorkspaceId(uuid.uuid4())

account_id = CloudAccountId("foobar")
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


class DomainEventSenderMock(DomainEventPublisher):
    def __init__(self) -> None:
        self.events: List[Event] = []

    async def publish(self, event: Event) -> None:
        return self.events.append(event)


class LastScanRepositoryMock(LastScanRepository):
    def __init__(self) -> None:
        self.data: Dict[WorkspaceId, LastScanInfo] = {}

    async def set_last_scan(self, workspace_id: WorkspaceId, last_scan_statistics: LastScanInfo) -> None:
        self.data[workspace_id] = last_scan_statistics

    async def get_last_scan(self, workspace_id: WorkspaceId) -> LastScanInfo | None:
        return self.data.get(workspace_id)


@pytest.mark.asyncio
async def test_create_aws_account(arq_redis: Redis) -> None:
    repository = CloudAccountRepositoryMock()
    organization_repository = OrganizationServiceMock()
    pubsub_publisher = RedisPubSubPublisherMock()
    domain_sender = DomainEventSenderMock()
    last_scan_repo = LastScanRepositoryMock()
    service = CloudAccountServiceImpl(
        organization_repository, repository, pubsub_publisher, domain_sender, last_scan_repo, arq_redis
    )

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

    assert pubsub_publisher.last_message is not None
    assert pubsub_publisher.last_message[0] == "cloud_account_created"
    assert pubsub_publisher.last_message[1] == message
    assert pubsub_publisher.last_message[2] == f"tenant-events::{test_workspace_id}"

    assert len(domain_sender.events) == 1
    event = domain_sender.events[0]
    assert isinstance(event, AwsAccountDiscovered)
    assert event.cloud_account_id == acc.id
    assert event.aws_account_id == account_id
    assert event.tenant_id == acc.workspace_id

    # account already exists
    idempotent_account = await service.create_aws_account(test_workspace_id, account_id, role_name, external_id)
    assert len(repository.accounts) == 1
    assert idempotent_account == acc

    # wrong external id
    with pytest.raises(Exception):
        await service.create_aws_account(test_workspace_id, account_id, role_name, ExternalId(uuid.uuid4()))

    # wrong tenant id
    with pytest.raises(Exception):
        await service.create_aws_account(WorkspaceId(uuid.uuid4()), account_id, role_name, external_id)


@pytest.mark.asyncio
async def test_delete_aws_account(arq_redis: Redis) -> None:
    repository = CloudAccountRepositoryMock()
    organization_repository = OrganizationServiceMock()
    pubsub_publisher = RedisPubSubPublisherMock()
    domain_sender = DomainEventSenderMock()
    last_scan_repo = LastScanRepositoryMock()
    service = CloudAccountServiceImpl(
        organization_repository, repository, pubsub_publisher, domain_sender, last_scan_repo, arq_redis
    )

    account = await service.create_aws_account(test_workspace_id, account_id, role_name, external_id)
    assert len(repository.accounts) == 1

    # deleting someone's else account
    with pytest.raises(Exception):
        await service.delete_cloud_account(account.id, WorkspaceId(uuid.uuid4()))
    assert len(repository.accounts) == 1

    # success
    await service.delete_cloud_account(account.id, test_workspace_id)
    assert len(repository.accounts) == 0


@pytest.mark.asyncio
async def test_store_last_run_info(arq_redis: Redis) -> None:
    repository = CloudAccountRepositoryMock()
    organization_repository = OrganizationServiceMock()
    pubsub_publisher = RedisPubSubPublisherMock()
    domain_sender = DomainEventSenderMock()
    last_scan_repo = LastScanRepositoryMock()
    service = CloudAccountServiceImpl(
        organization_repository, repository, pubsub_publisher, domain_sender, last_scan_repo, arq_redis
    )

    cloud_account_id = FixCloudAccountId(uuid.uuid4())
    now = datetime.utcnow()
    event = TenantAccountsCollected(
        test_workspace_id, {cloud_account_id: CloudAccountCollectInfo(account_id, 100, 10, now)}, now
    )
    await service.process_domain_event(
        event.to_json(),
        MessageContext(id="test", kind=TenantAccountsCollected.kind, publisher="test", sent_at=now, received_at=now),
    )

    last_scan = await service.last_scan(test_workspace_id)
    assert last_scan is not None
    assert last_scan.next_scan == now
    account = last_scan.accounts[cloud_account_id]
    assert account.account_id == account_id
    assert account.duration_seconds == 10
    assert account.resources_scanned == 100
    assert account.started_at == now
