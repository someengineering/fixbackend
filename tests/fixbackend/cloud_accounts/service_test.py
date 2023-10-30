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
from fixbackend.domain_events.events import AwsAccountDiscovered, Event, AwsAccountConfigured
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.ids import FixCloudAccountId, ExternalId, WorkspaceId, CloudAccountId
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepositoryImpl
from fixbackend.domain_events.events import TenantAccountsCollected, CloudAccountCollectInfo
from datetime import datetime
from fixcloudutils.redis.event_stream import MessageContext
from fixbackend.cloud_accounts.last_scan_repository import LastScanRepository
from fixbackend.config import Config
from fixbackend.cloud_accounts.account_setup import AwsAccountSetupHelper
from fixbackend.errors import ResourceNotFound, AccessDenied


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

    async def list_by_workspace_id(
        self, workspace_id: WorkspaceId, enabled: Optional[bool] = None, configured: Optional[bool] = None
    ) -> List[CloudAccount]:
        accounts = [account for account in self.accounts.values() if account.workspace_id == workspace_id]
        if enabled is not None:
            accounts = [account for account in accounts if account.enabled == enabled]
        if configured is not None:
            accounts = [account for account in accounts if account.is_configured == configured]
        return accounts

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


class AwsAccountSetupHelperMock(AwsAccountSetupHelper):
    def __init__(self) -> None:
        self.can_assume = True

    async def can_assume_role(self, account_id: str, role_name: str) -> bool:
        return self.can_assume


@pytest.mark.asyncio
async def test_create_aws_account(
    arq_redis: Redis,
    default_config: Config,
) -> None:
    repository = CloudAccountRepositoryMock()
    organization_repository = OrganizationServiceMock()
    pubsub_publisher = RedisPubSubPublisherMock()
    domain_sender = DomainEventSenderMock()
    last_scan_repo = LastScanRepositoryMock()
    account_setup_helper = AwsAccountSetupHelperMock()
    service = CloudAccountServiceImpl(
        organization_repository,
        repository,
        pubsub_publisher,
        domain_sender,
        last_scan_repo,
        arq_redis,
        default_config,
        account_setup_helper,
    )

    # happy case
    acc = await service.create_aws_account(test_workspace_id, account_id, role_name, external_id)
    assert len(repository.accounts) == 1
    account = repository.accounts.get(acc.id)
    assert account is not None
    assert account.workspace_id == test_workspace_id
    assert isinstance(account.access, AwsCloudAccess)
    assert account.access.aws_account_id == account_id
    assert account.access.role_name == role_name
    assert account.access.external_id == external_id
    assert account.name is None
    assert account.is_configured is False
    assert account.enabled is True

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
async def test_delete_aws_account(arq_redis: Redis, default_config: Config) -> None:
    repository = CloudAccountRepositoryMock()
    organization_repository = OrganizationServiceMock()
    pubsub_publisher = RedisPubSubPublisherMock()
    domain_sender = DomainEventSenderMock()
    last_scan_repo = LastScanRepositoryMock()
    account_setup_helper = AwsAccountSetupHelperMock()
    service = CloudAccountServiceImpl(
        organization_repository,
        repository,
        pubsub_publisher,
        domain_sender,
        last_scan_repo,
        arq_redis,
        default_config,
        account_setup_helper,
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
async def test_store_last_run_info(arq_redis: Redis, default_config: Config) -> None:
    repository = CloudAccountRepositoryMock()
    organization_repository = OrganizationServiceMock()
    pubsub_publisher = RedisPubSubPublisherMock()
    domain_sender = DomainEventSenderMock()
    last_scan_repo = LastScanRepositoryMock()
    account_setup_helper = AwsAccountSetupHelperMock()
    service = CloudAccountServiceImpl(
        organization_repository,
        repository,
        pubsub_publisher,
        domain_sender,
        last_scan_repo,
        arq_redis,
        default_config,
        account_setup_helper,
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


@pytest.mark.asyncio
async def test_get_cloud_account(arq_redis: Redis, default_config: Config) -> None:
    repository = CloudAccountRepositoryMock()
    organization_repository = OrganizationServiceMock()
    pubsub_publisher = RedisPubSubPublisherMock()
    domain_sender = DomainEventSenderMock()
    last_scan_repo = LastScanRepositoryMock()
    account_setup_helper = AwsAccountSetupHelperMock()
    service = CloudAccountServiceImpl(
        organization_repository,
        repository,
        pubsub_publisher,
        domain_sender,
        last_scan_repo,
        arq_redis,
        default_config,
        account_setup_helper,
    )

    account = await service.create_aws_account(test_workspace_id, account_id, role_name, external_id)
    assert len(repository.accounts) == 1

    # success
    cloud_account = await service.get_cloud_account(account.id, test_workspace_id)
    assert cloud_account is not None
    assert cloud_account.id == account.id
    assert cloud_account.access.cloud == "aws"
    assert cloud_account.access.account_id() == account_id

    # wrong tenant id
    with pytest.raises(AccessDenied):
        await service.get_cloud_account(account.id, WorkspaceId(uuid.uuid4()))

    # wrong account id
    with pytest.raises(ResourceNotFound):
        await service.get_cloud_account(FixCloudAccountId(uuid.uuid4()), test_workspace_id)


@pytest.mark.asyncio
async def test_list_cloud_accounts(arq_redis: Redis, default_config: Config) -> None:
    repository = CloudAccountRepositoryMock()
    organization_repository = OrganizationServiceMock()
    pubsub_publisher = RedisPubSubPublisherMock()
    domain_sender = DomainEventSenderMock()
    last_scan_repo = LastScanRepositoryMock()
    account_setup_helper = AwsAccountSetupHelperMock()
    service = CloudAccountServiceImpl(
        organization_repository,
        repository,
        pubsub_publisher,
        domain_sender,
        last_scan_repo,
        arq_redis,
        default_config,
        account_setup_helper,
    )

    account = await service.create_aws_account(test_workspace_id, account_id, role_name, external_id)
    assert len(repository.accounts) == 1

    # success
    cloud_accounts = await service.list_accounts(test_workspace_id)
    assert len(cloud_accounts) == 1
    assert cloud_accounts[0].id == account.id
    assert cloud_accounts[0].access.cloud == "aws"
    assert cloud_accounts[0].access.account_id() == account_id
    assert cloud_accounts[0].name is None

    # wrong tenant id
    non_existing_tenant = await service.list_accounts(WorkspaceId(uuid.uuid4()))
    assert len(non_existing_tenant) == 0


@pytest.mark.asyncio
async def test_update_cloud_account_name(arq_redis: Redis, default_config: Config) -> None:
    repository = CloudAccountRepositoryMock()
    organization_repository = OrganizationServiceMock()
    pubsub_publisher = RedisPubSubPublisherMock()
    domain_sender = DomainEventSenderMock()
    last_scan_repo = LastScanRepositoryMock()
    account_setup_helper = AwsAccountSetupHelperMock()
    service = CloudAccountServiceImpl(
        organization_repository,
        repository,
        pubsub_publisher,
        domain_sender,
        last_scan_repo,
        arq_redis,
        default_config,
        account_setup_helper,
    )

    account = await service.create_aws_account(test_workspace_id, account_id, role_name, external_id)
    assert len(repository.accounts) == 1

    # success
    updated = await service.update_cloud_account_name(test_workspace_id, account.id, "foo")
    assert updated.name == "foo"
    assert updated.id == account.id
    assert updated.access == account.access
    assert updated.workspace_id == account.workspace_id

    # wrong tenant id
    with pytest.raises(AccessDenied):
        await service.update_cloud_account_name(WorkspaceId(uuid.uuid4()), account.id, "foo")

    # wrong account id
    with pytest.raises(ResourceNotFound):
        await service.update_cloud_account_name(test_workspace_id, FixCloudAccountId(uuid.uuid4()), "foo")


@pytest.mark.asyncio
async def test_handle_account_discovered(arq_redis: Redis, default_config: Config) -> None:
    repository = CloudAccountRepositoryMock()
    organization_repository = OrganizationServiceMock()
    pubsub_publisher = RedisPubSubPublisherMock()
    domain_sender = DomainEventSenderMock()
    last_scan_repo = LastScanRepositoryMock()
    account_setup_helper = AwsAccountSetupHelperMock()
    service = CloudAccountServiceImpl(
        organization_repository,
        repository,
        pubsub_publisher,
        domain_sender,
        last_scan_repo,
        arq_redis,
        default_config,
        account_setup_helper,
    )

    account = await service.create_aws_account(test_workspace_id, account_id, role_name, external_id)
    assert len(repository.accounts) == 1

    assert len(domain_sender.events) == 1
    event = domain_sender.events[0]
    assert isinstance(event, AwsAccountDiscovered)

    # happy case, boto3 can assume role
    await service.process_domain_event(
        event.to_json(), MessageContext("test", event.kind, "test", datetime.utcnow(), datetime.utcnow())
    )

    assert len(domain_sender.events) == 2
    event = domain_sender.events[1]
    assert isinstance(event, AwsAccountConfigured)
    assert event.cloud_account_id == account.id
    assert event.aws_account_id == account_id
    assert event.tenant_id == account.workspace_id

    # boto3 cannot assume right away
    account_id1 = CloudAccountId("foobar1")
    role_name1 = "FooBarRole1"
    account1 = await service.create_aws_account(test_workspace_id, account_id1, role_name1, external_id)
    assert len(repository.accounts) == 2
    event = domain_sender.events[2]

    account_setup_helper.can_assume = False

    with pytest.raises(Exception):
        await service.process_domain_event(
            event.to_json(), MessageContext("test", event.kind, "test", datetime.utcnow(), datetime.utcnow())
        )
    # no event should be published before the account is configured
    assert len(domain_sender.events) == 3

    # now boto3 can assume role and event should be published
    account_setup_helper.can_assume = True
    await service.process_domain_event(
        event.to_json(), MessageContext("test", event.kind, "test", datetime.utcnow(), datetime.utcnow())
    )
    assert len(domain_sender.events) == 4
    event = domain_sender.events[3]
    assert isinstance(event, AwsAccountConfigured)
    assert event.cloud_account_id == account1.id
    assert event.aws_account_id == account_id1
    assert event.tenant_id == account1.workspace_id


@pytest.mark.asyncio
async def test_handle_account_configured(arq_redis: Redis, default_config: Config) -> None:
    repository = CloudAccountRepositoryMock()
    organization_repository = OrganizationServiceMock()
    pubsub_publisher = RedisPubSubPublisherMock()
    domain_sender = DomainEventSenderMock()
    last_scan_repo = LastScanRepositoryMock()
    account_setup_helper = AwsAccountSetupHelperMock()
    service = CloudAccountServiceImpl(
        organization_repository,
        repository,
        pubsub_publisher,
        domain_sender,
        last_scan_repo,
        arq_redis,
        default_config,
        account_setup_helper,
    )

    account = await service.create_aws_account(test_workspace_id, account_id, role_name, external_id)
    assert account.is_configured is False

    event = AwsAccountConfigured(
        cloud_account_id=account.id,
        tenant_id=account.workspace_id,
        aws_account_id=account_id,
    )
    # happy case, boto3 can assume role
    await service.process_domain_event(
        event.to_json(), MessageContext("test", event.kind, "test", datetime.utcnow(), datetime.utcnow())
    )

    after_configured = await service.get_cloud_account(account.id, test_workspace_id)
    assert after_configured is not None
    assert after_configured.is_configured is True
    assert after_configured.access == account.access
    assert after_configured.workspace_id == account.workspace_id
    assert after_configured.name == account.name
    assert after_configured.id == account.id
    assert after_configured.enabled == account.enabled


@pytest.mark.asyncio
async def test_enable_disable_cloud_account(arq_redis: Redis, default_config: Config) -> None:
    repository = CloudAccountRepositoryMock()
    organization_repository = OrganizationServiceMock()
    pubsub_publisher = RedisPubSubPublisherMock()
    domain_sender = DomainEventSenderMock()
    last_scan_repo = LastScanRepositoryMock()
    account_setup_helper = AwsAccountSetupHelperMock()
    service = CloudAccountServiceImpl(
        organization_repository,
        repository,
        pubsub_publisher,
        domain_sender,
        last_scan_repo,
        arq_redis,
        default_config,
        account_setup_helper,
    )

    account = await service.create_aws_account(test_workspace_id, account_id, role_name, external_id)
    assert len(repository.accounts) == 1

    # success
    updated = await service.enable_cloud_account(
        test_workspace_id,
        account.id,
    )
    assert updated.enabled is True
    assert repository.accounts[account.id].enabled is True

    updated = await service.disable_cloud_account(
        test_workspace_id,
        account.id,
    )
    assert updated.enabled is False
    assert repository.accounts[account.id].enabled is False

    # wrong tenant id
    with pytest.raises(Exception):
        await service.update_cloud_account_name(WorkspaceId(uuid.uuid4()), account.id, "foo")

    # wrong account id
    with pytest.raises(Exception):
        await service.update_cloud_account_name(test_workspace_id, FixCloudAccountId(uuid.uuid4()), "foo")
