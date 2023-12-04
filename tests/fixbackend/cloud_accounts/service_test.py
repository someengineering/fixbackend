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
import json
import uuid
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

import boto3
import pytest
from attrs import evolve
from fixcloudutils.redis.event_stream import MessageContext, RedisStreamPublisher
from fixcloudutils.redis.pub_sub import RedisPubSubPublisher
from fixcloudutils.types import Json
from httpx import AsyncClient, Request, Response
from redis.asyncio import Redis

from fixbackend.cloud_accounts.account_setup import AssumeRoleResult, AssumeRoleResults, AwsAccountSetupHelper
from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount, CloudAccountStates
from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.cloud_accounts.service_impl import CloudAccountServiceImpl
from fixbackend.config import Config
from fixbackend.domain_events.events import (
    AwsAccountConfigured,
    AwsAccountDiscovered,
    CloudAccountCollectInfo,
    Event,
    TenantAccountsCollected,
    AwsAccountDegraded,
)
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.errors import AccessDenied, ResourceNotFound
from fixbackend.ids import (
    AwsRoleName,
    CloudAccountAlias,
    CloudAccountId,
    CloudAccountName,
    CloudNames,
    ExternalId,
    FixCloudAccountId,
    UserCloudAccountName,
    WorkspaceId,
)
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepositoryImpl
from fixcloudutils.util import utc

from tests.fixbackend.conftest import RequestHandlerMock


class CloudAccountRepositoryMock(CloudAccountRepository):
    def __init__(self) -> None:
        self.accounts: Dict[FixCloudAccountId, CloudAccount] = {}

    async def create(self, cloud_account: CloudAccount) -> CloudAccount:
        self.accounts[cloud_account.id] = cloud_account
        return cloud_account

    async def get(self, id: FixCloudAccountId) -> CloudAccount | None:
        return self.accounts.get(id)

    async def update(self, id: FixCloudAccountId, update_fn: Callable[[CloudAccount], CloudAccount]) -> CloudAccount:
        self.accounts[id] = update_fn(self.accounts[id])
        return self.accounts[id]

    async def list_by_workspace_id(
        self, workspace_id: WorkspaceId, ready_for_collection: Optional[bool] = None
    ) -> List[CloudAccount]:
        accounts = [
            account
            for account in self.accounts.values()
            if account.workspace_id == workspace_id and account.state != CloudAccountStates.Deleted()
        ]
        if ready_for_collection is not None:
            accounts = [
                account
                for account in accounts
                if isinstance(account.state, (CloudAccountStates.Configured, CloudAccountStates.Degraded))
            ]
        return accounts

    async def delete(self, id: FixCloudAccountId) -> None:
        self.accounts.pop(id)

    async def list_all_discovered_accounts(self) -> List[CloudAccount]:
        return [
            account for account in self.accounts.values() if isinstance(account.state, CloudAccountStates.Discovered)
        ]


test_workspace_id = WorkspaceId(uuid.uuid4())

account_id = CloudAccountId("foobar")
role_name = AwsRoleName("FooBarRole")
external_id = ExternalId(uuid.uuid4())
account_name = CloudAccountName("foobar-account-name")
user_account_name = UserCloudAccountName("foobar-user-account-name")
account_alias = CloudAccountAlias("foobar-account-alias")


organization = Workspace(
    id=test_workspace_id,
    name="Test Organization",
    slug="test-organization",
    external_id=external_id,
    owners=[],
    members=[],
)


class OrganizationServiceMock(WorkspaceRepositoryImpl):
    # noinspection PyMissingConstructor
    def __init__(self) -> None:
        pass

    async def get_workspace(self, workspace_id: WorkspaceId, with_users: bool = False) -> Workspace | None:
        if workspace_id != test_workspace_id:
            return None
        return organization


class RedisStreamPublisherMock(RedisStreamPublisher):
    # noinspection PyMissingConstructor
    def __init__(self) -> None:
        self.last_message: Optional[Tuple[str, Json]] = None

    async def publish(self, kind: str, message: Json) -> None:
        self.last_message = (kind, message)


class RedisPubSubPublisherMock(RedisPubSubPublisher):
    # noinspection PyMissingConstructor
    def __init__(self) -> None:
        self.last_message: Optional[Tuple[str, Json, Optional[str]]] = None

    async def publish(self, kind: str, message: Json, channel: Optional[str] = None) -> None:
        self.last_message = (kind, message, channel)


class DomainEventSenderMock(DomainEventPublisher):
    def __init__(self) -> None:
        self.events: List[Event] = []

    async def publish(self, event: Event) -> None:
        return self.events.append(event)


class AwsAccountSetupHelperMock(AwsAccountSetupHelper):
    # noinspection PyMissingConstructor
    def __init__(self) -> None:
        self.can_assume = True
        self.can_describe_regions = True
        self.org_accounts: Dict[CloudAccountId, CloudAccountName] = {}
        self.account_alias: CloudAccountAlias | None = None

    async def can_assume_role(
        self, account_id: str, role_name: AwsRoleName, external_id: ExternalId
    ) -> AssumeRoleResult:
        if self.can_assume:
            return AssumeRoleResults.Success("foo", "bar", "baz", datetime.utcnow())
        return AssumeRoleResults.Failure("Cannot assume role")

    async def list_accounts(
        self, assume_role_result: AssumeRoleResults.Success
    ) -> Dict[CloudAccountId, CloudAccountName]:
        return self.org_accounts

    async def list_account_aliases(self, assume_role_result: AssumeRoleResults.Success) -> CloudAccountAlias | None:
        return self.account_alias

    async def allowed_to_describe_regions(self, result: AssumeRoleResults.Success) -> None:
        if not self.can_describe_regions:
            raise Exception("Not allowed to describe regions")


now = datetime.utcnow()


@pytest.fixture
def repository() -> CloudAccountRepositoryMock:
    return CloudAccountRepositoryMock()


@pytest.fixture
def organization_repository() -> OrganizationServiceMock:
    return OrganizationServiceMock()


@pytest.fixture
def pubsub_publisher() -> RedisPubSubPublisherMock:
    return RedisPubSubPublisherMock()


@pytest.fixture
def domain_sender() -> DomainEventSenderMock:
    return DomainEventSenderMock()


@pytest.fixture
def account_setup_helper() -> AwsAccountSetupHelperMock:
    return AwsAccountSetupHelperMock()


@pytest.fixture
def service(
    organization_repository: OrganizationServiceMock,
    repository: CloudAccountRepositoryMock,
    pubsub_publisher: RedisPubSubPublisherMock,
    domain_sender: DomainEventSenderMock,
    account_setup_helper: AwsAccountSetupHelperMock,
    arq_redis: Redis,
    default_config: Config,
    boto_session: boto3.Session,
    http_client: AsyncClient,
) -> CloudAccountServiceImpl:
    return CloudAccountServiceImpl(
        organization_repository,
        repository,
        pubsub_publisher,
        domain_sender,
        arq_redis,
        default_config,
        account_setup_helper,
        dispatching=False,
        boto_session=boto_session,
        http_client=http_client,
        cf_stack_queue_url=None,
    )


@pytest.mark.asyncio
async def test_create_aws_account(
    repository: CloudAccountRepositoryMock,
    pubsub_publisher: RedisPubSubPublisherMock,
    domain_sender: DomainEventSenderMock,
    service: CloudAccountServiceImpl,
) -> None:
    # happy case
    acc = await service.create_aws_account(
        workspace_id=test_workspace_id,
        account_id=account_id,
        role_name=role_name,
        external_id=external_id,
        account_name=account_name,
    )
    assert len(repository.accounts) == 1
    account = repository.accounts.get(acc.id)
    assert account is not None
    assert account.workspace_id == test_workspace_id
    assert account.account_id == account_id
    assert account.account_name == account_name
    assert isinstance(account.state, CloudAccountStates.Discovered)
    assert isinstance(account.state.access, AwsCloudAccess)
    assert account.state.access.role_name == role_name
    assert account.state.access.external_id == external_id

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

    # account already exists, account_name should be updated, but nothing else
    idempotent_account = await service.create_aws_account(
        workspace_id=test_workspace_id,
        account_id=account_id,
        role_name=None,
        external_id=external_id,
        account_name=account_name,
    )
    # no extra account should be created
    assert len(repository.accounts) == 1
    # domain event should not be published
    assert len(domain_sender.events) == 1
    assert idempotent_account == acc

    # account already exists, account_name should be updated, but nothing else
    with_updated_name = await service.create_aws_account(
        workspace_id=test_workspace_id,
        account_id=account_id,
        role_name=None,
        external_id=external_id,
        account_name=CloudAccountName("foobar"),
    )
    assert len(repository.accounts) == 1
    # domain event should not be published
    assert len(domain_sender.events) == 1
    assert with_updated_name.workspace_id == acc.workspace_id
    assert with_updated_name.state == acc.state
    assert with_updated_name.account_name == CloudAccountName("foobar")
    assert with_updated_name.user_account_name == acc.user_account_name
    assert with_updated_name.id == acc.id
    assert with_updated_name.account_alias == acc.account_alias

    # account with role_name=None should end up as detected not create any events
    detected_account_id = CloudAccountId("foobar2")
    detected_account = await service.create_aws_account(
        workspace_id=test_workspace_id,
        account_id=detected_account_id,
        role_name=None,
        external_id=external_id,
        account_name=account_name,
    )
    assert detected_account.state == CloudAccountStates.Detected()
    # a new account should be created
    assert len(repository.accounts) == 2
    # domain event should not be published
    assert len(domain_sender.events) == 1

    # wrong external id
    with pytest.raises(Exception):
        await service.create_aws_account(
            workspace_id=test_workspace_id,
            account_id=account_id,
            role_name=role_name,
            external_id=ExternalId(uuid.uuid4()),
            account_name=None,
        )

    # wrong tenant id
    with pytest.raises(Exception):
        await service.create_aws_account(
            workspace_id=WorkspaceId(uuid.uuid4()),
            account_id=account_id,
            role_name=role_name,
            external_id=external_id,
            account_name=None,
        )


@pytest.mark.asyncio
async def test_delete_aws_account(
    repository: CloudAccountRepositoryMock,
    service: CloudAccountServiceImpl,
) -> None:
    account = await service.create_aws_account(
        workspace_id=test_workspace_id,
        account_id=account_id,
        role_name=role_name,
        external_id=external_id,
        account_name=None,
    )
    assert len(repository.accounts) == 1

    # deleting someone's else account
    with pytest.raises(Exception):
        await service.delete_cloud_account(account.id, WorkspaceId(uuid.uuid4()))
    assert len(repository.accounts) == 1

    # success
    await service.delete_cloud_account(account.id, test_workspace_id)
    assert len(repository.accounts) == 1
    assert isinstance(repository.accounts[account.id].state, CloudAccountStates.Deleted)


@pytest.mark.asyncio
async def test_store_last_run_info(service: CloudAccountServiceImpl) -> None:
    account = await service.create_aws_account(
        workspace_id=test_workspace_id,
        account_id=account_id,
        role_name=role_name,
        external_id=external_id,
        account_name=None,
    )

    cloud_account_id = account.id
    now = datetime.utcnow()
    event = TenantAccountsCollected(
        test_workspace_id, {cloud_account_id: CloudAccountCollectInfo(account_id, 100, 10, now)}, now
    )
    await service.process_domain_event(
        event.to_json(),
        MessageContext(id="test", kind=TenantAccountsCollected.kind, publisher="test", sent_at=now, received_at=now),
    )

    account = await service.get_cloud_account(cloud_account_id, test_workspace_id)

    assert account.next_scan == now
    assert account.account_id == account_id
    assert account.last_scan_duration_seconds == 10
    assert account.last_scan_resources_scanned == 100
    assert account.last_scan_started_at == now


@pytest.mark.asyncio
async def test_get_cloud_account(repository: CloudAccountRepositoryMock, service: CloudAccountServiceImpl) -> None:
    account = await service.create_aws_account(
        workspace_id=test_workspace_id,
        account_id=account_id,
        role_name=role_name,
        external_id=external_id,
        account_name=account_name,
    )
    assert len(repository.accounts) == 1

    # success
    cloud_account = await service.get_cloud_account(account.id, test_workspace_id)
    assert cloud_account is not None
    assert cloud_account.id == account.id
    assert cloud_account.cloud == CloudNames.AWS
    assert cloud_account.account_id == account_id
    assert cloud_account.account_name == account_name
    assert isinstance(cloud_account.state, CloudAccountStates.Discovered)
    assert isinstance(cloud_account.state.access, AwsCloudAccess)

    assert cloud_account.account_alias is None
    assert cloud_account.user_account_name is None

    # wrong tenant id
    with pytest.raises(AccessDenied):
        await service.get_cloud_account(account.id, WorkspaceId(uuid.uuid4()))

    # wrong account id
    with pytest.raises(ResourceNotFound):
        await service.get_cloud_account(FixCloudAccountId(uuid.uuid4()), test_workspace_id)


@pytest.mark.asyncio
async def test_list_cloud_accounts(repository: CloudAccountRepositoryMock, service: CloudAccountServiceImpl) -> None:
    account = await service.create_aws_account(
        workspace_id=test_workspace_id,
        account_id=account_id,
        role_name=role_name,
        external_id=external_id,
        account_name=None,
    )
    assert len(repository.accounts) == 1

    # success
    cloud_accounts = await service.list_accounts(test_workspace_id)
    assert len(cloud_accounts) == 1
    assert cloud_accounts[0].id == account.id
    assert cloud_accounts[0].cloud == CloudNames.AWS
    assert cloud_accounts[0].account_id == account_id
    assert cloud_accounts[0].account_name is None

    # wrong tenant id
    non_existing_tenant = await service.list_accounts(WorkspaceId(uuid.uuid4()))
    assert len(non_existing_tenant) == 0


@pytest.mark.asyncio
async def test_update_cloud_account_name(
    repository: CloudAccountRepositoryMock, service: CloudAccountServiceImpl
) -> None:
    account = await service.create_aws_account(
        workspace_id=test_workspace_id,
        account_id=account_id,
        role_name=role_name,
        external_id=external_id,
        account_name=account_name,
    )
    assert len(repository.accounts) == 1

    # success
    updated = await service.update_cloud_account_name(test_workspace_id, account.id, user_account_name)
    assert updated.user_account_name == user_account_name
    assert updated.account_name == account_name
    assert updated.account_alias is None
    assert updated.id == account.id
    assert updated.state == account.state
    assert updated.workspace_id == account.workspace_id

    # set name to None
    updated = await service.update_cloud_account_name(test_workspace_id, account.id, None)
    assert updated.user_account_name is None
    assert updated.account_name == account_name
    assert updated.id == account.id
    assert updated.state == account.state
    assert updated.workspace_id == account.workspace_id

    # wrong tenant id
    with pytest.raises(AccessDenied):
        await service.update_cloud_account_name(WorkspaceId(uuid.uuid4()), account.id, user_account_name)

    # wrong account id
    with pytest.raises(ResourceNotFound):
        await service.update_cloud_account_name(test_workspace_id, FixCloudAccountId(uuid.uuid4()), user_account_name)


@pytest.mark.asyncio
async def test_handle_account_discovered_success(
    repository: CloudAccountRepositoryMock,
    domain_sender: DomainEventSenderMock,
    service: CloudAccountServiceImpl,
) -> None:
    # allowed to perform describe regions
    account = await service.create_aws_account(
        workspace_id=test_workspace_id,
        account_id=account_id,
        role_name=role_name,
        external_id=external_id,
        account_name=None,
    )
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


@pytest.mark.asyncio
async def test_handle_account_discovered_assume_role_success(
    repository: CloudAccountRepositoryMock,
    domain_sender: DomainEventSenderMock,
    service: CloudAccountServiceImpl,
    account_setup_helper: AwsAccountSetupHelperMock,
) -> None:
    await service.create_aws_account(
        workspace_id=test_workspace_id,
        account_id=CloudAccountId("foobar"),
        role_name=AwsRoleName("FooBarRole"),
        external_id=external_id,
        account_name=None,
    )
    event = domain_sender.events[0]
    account_setup_helper.can_assume = True
    account_setup_helper.can_describe_regions = False
    # boto3 can not describe regions -> fail
    with pytest.raises(Exception):
        await service.process_domain_event(
            event.to_json(), MessageContext("test", event.kind, "test", datetime.utcnow(), datetime.utcnow())
        )


@pytest.mark.asyncio
async def test_handle_account_discovered_assume_role_failure(
    repository: CloudAccountRepositoryMock,
    domain_sender: DomainEventSenderMock,
    service: CloudAccountServiceImpl,
    account_setup_helper: AwsAccountSetupHelperMock,
) -> None:
    # boto3 cannot assume right away
    account_id = CloudAccountId("foobar")
    role_name = AwsRoleName("FooBarRole")
    account = await service.create_aws_account(
        workspace_id=test_workspace_id,
        account_id=account_id,
        role_name=role_name,
        external_id=external_id,
        account_name=None,
    )
    assert len(repository.accounts) == 1
    assert len(domain_sender.events) == 1
    event = domain_sender.events[0]

    account_setup_helper.can_assume = False

    with pytest.raises(Exception):
        await service.process_domain_event(
            event.to_json(), MessageContext("test", event.kind, "test", datetime.utcnow(), datetime.utcnow())
        )
    # no event should be published before the account is configured
    assert len(domain_sender.events) == 1

    # now boto3 can assume role and event should be published
    account_setup_helper.can_assume = True
    await service.process_domain_event(
        event.to_json(), MessageContext("test", event.kind, "test", datetime.utcnow(), datetime.utcnow())
    )
    assert len(domain_sender.events) == 2
    event = domain_sender.events[1]
    assert isinstance(event, AwsAccountConfigured)
    assert event.cloud_account_id == account.id
    assert event.aws_account_id == account_id
    assert event.tenant_id == account.workspace_id

    after_configured = await service.get_cloud_account(account.id, test_workspace_id)

    assert after_configured is not None
    assert after_configured.privileged is False
    assert after_configured.state == CloudAccountStates.Configured(AwsCloudAccess(external_id, role_name), enabled=True)
    assert after_configured.workspace_id == account.workspace_id
    assert after_configured.account_name == account.account_name
    assert after_configured.id == account.id
    assert after_configured.account_id == account.account_id


@pytest.mark.asyncio
async def test_handle_account_discovered_list_accounts_success(
    repository: CloudAccountRepositoryMock,
    domain_sender: DomainEventSenderMock,
    service: CloudAccountServiceImpl,
    account_setup_helper: AwsAccountSetupHelperMock,
) -> None:
    account_id = CloudAccountId("foobar")
    role_name = AwsRoleName("FooBarRole")
    account = await service.create_aws_account(
        workspace_id=test_workspace_id,
        account_id=account_id,
        role_name=role_name,
        external_id=external_id,
        account_name=None,
    )
    assert len(repository.accounts) == 1
    assert len(domain_sender.events) == 1
    event = domain_sender.events[0]

    account_setup_helper.can_assume = True
    account_setup_helper.org_accounts = {account_id: account_name}

    await service.process_domain_event(
        event.to_json(), MessageContext("test", event.kind, "test", datetime.utcnow(), datetime.utcnow())
    )
    assert len(domain_sender.events) == 2
    event = domain_sender.events[1]
    assert isinstance(event, AwsAccountConfigured)

    after_discovered = await service.get_cloud_account(account.id, test_workspace_id)

    assert after_discovered is not None
    assert after_discovered.workspace_id == account.workspace_id
    assert after_discovered.account_name == account_name
    assert after_discovered.id == account.id
    assert after_discovered.account_id == account.account_id
    assert after_discovered.privileged is True

    assert after_discovered.state == CloudAccountStates.Configured(AwsCloudAccess(external_id, role_name), enabled=True)


@pytest.mark.asyncio
async def test_handle_account_discovered_list_aliases_success(
    repository: CloudAccountRepositoryMock,
    domain_sender: DomainEventSenderMock,
    service: CloudAccountServiceImpl,
    account_setup_helper: AwsAccountSetupHelperMock,
) -> None:
    # boto3 cannot assume right away
    account_id = CloudAccountId("foobar")
    role_name = AwsRoleName("FooBarRole")
    account = await service.create_aws_account(
        workspace_id=test_workspace_id,
        account_id=account_id,
        role_name=role_name,
        external_id=external_id,
        account_name=None,
    )
    assert len(repository.accounts) == 1
    assert len(domain_sender.events) == 1
    event = domain_sender.events[0]

    account_setup_helper.can_assume = True
    account_setup_helper.org_accounts = {}
    account_setup_helper.account_alias = account_alias

    await service.process_domain_event(
        event.to_json(), MessageContext("test", event.kind, "test", datetime.utcnow(), datetime.utcnow())
    )
    assert len(domain_sender.events) == 2
    event = domain_sender.events[1]
    assert isinstance(event, AwsAccountConfigured)

    after_discovered = await service.get_cloud_account(account.id, test_workspace_id)

    assert after_discovered is not None
    assert after_discovered.workspace_id == account.workspace_id
    assert after_discovered.account_name is None
    assert after_discovered.account_alias == account_alias
    assert after_discovered.id == account.id
    assert after_discovered.account_id == account.account_id
    assert after_discovered.privileged is False
    assert after_discovered.state == CloudAccountStates.Configured(AwsCloudAccess(external_id, role_name), enabled=True)


@pytest.mark.asyncio
async def test_enable_disable_cloud_account(
    repository: CloudAccountRepositoryMock, service: CloudAccountServiceImpl
) -> None:
    account = await service.create_aws_account(
        workspace_id=test_workspace_id,
        account_id=account_id,
        role_name=role_name,
        external_id=external_id,
        account_name=None,
    )
    assert len(repository.accounts) == 1

    # account is not configured, cannot be enabled
    with pytest.raises(Exception):
        await service.enable_cloud_account(WorkspaceId(uuid.uuid4()), account.id)

    repository.accounts[account.id] = evolve(
        account,
        state=CloudAccountStates.Configured(AwsCloudAccess(external_id, role_name), enabled=False),
        privileged=False,
    )

    # success
    updated = await service.enable_cloud_account(
        test_workspace_id,
        account.id,
    )
    assert isinstance(updated.state, CloudAccountStates.Configured)
    assert updated.state.access == AwsCloudAccess(external_id, role_name)
    assert updated.privileged is False
    assert updated.state.enabled is True
    assert isinstance(repository.accounts[account.id].state, CloudAccountStates.Configured)

    updated = await service.disable_cloud_account(
        test_workspace_id,
        account.id,
    )
    assert isinstance(updated.state, CloudAccountStates.Configured)
    assert updated.state.access == AwsCloudAccess(external_id, role_name)
    assert updated.privileged is False
    assert updated.state.enabled is False

    # does not work for degraded accounts
    repository.accounts[account.id] = evolve(
        account,
        state=CloudAccountStates.Degraded(AwsCloudAccess(external_id, role_name), error="test error"),
        privileged=False,
    )

    with pytest.raises(Exception):
        await service.enable_cloud_account(
            test_workspace_id,
            account.id,
        )

    # wrong tenant id
    with pytest.raises(Exception):
        await service.update_cloud_account_name(WorkspaceId(uuid.uuid4()), account.id, user_account_name)

    # wrong account id
    with pytest.raises(Exception):
        await service.update_cloud_account_name(test_workspace_id, FixCloudAccountId(uuid.uuid4()), user_account_name)


@pytest.mark.asyncio
async def test_configure_account(
    repository: CloudAccountRepositoryMock,
    domain_sender: DomainEventSenderMock,
    service: CloudAccountServiceImpl,
    account_setup_helper: AwsAccountSetupHelperMock,
) -> None:
    account_setup_helper.can_assume = False

    def get_account(state_updated_at: datetime) -> CloudAccount:
        return CloudAccount(
            id=FixCloudAccountId(uuid.uuid4()),
            account_id=account_id,
            workspace_id=WorkspaceId(uuid.uuid4()),
            cloud=CloudNames.AWS,
            state=CloudAccountStates.Discovered(AwsCloudAccess(external_id, role_name)),
            account_name=CloudAccountName("foo"),
            account_alias=CloudAccountAlias("foo_alias"),
            user_account_name=UserCloudAccountName("foo_user"),
            privileged=True,
            last_scan_duration_seconds=10,
            last_scan_resources_scanned=100,
            last_scan_started_at=datetime.utcnow(),
            next_scan=utc(),
            created_at=utc(),
            updated_at=utc(),
            state_updated_at=state_updated_at,
        )

    # fresh account should be retried
    with pytest.raises(Exception):
        await service.configure_account(get_account(state_updated_at=utc()), called_from_event=True)

    with pytest.raises(Exception):
        await service.configure_account(get_account(state_updated_at=utc()), called_from_event=False)

    # more than 1 minute old account should go off fast_lane in case this was an event
    await service.configure_account(
        get_account(state_updated_at=utc() - (service.fast_lane_timeout + timedelta(minutes=1))), called_from_event=True
    )
    await service.configure_account(
        get_account(state_updated_at=utc() - (service.become_degraded_timeout + timedelta(minutes=1))),
        called_from_event=True,
    )
    assert len(domain_sender.events) == 0
    # but not if called from the periodic task
    with pytest.raises(Exception):
        await service.configure_account(
            get_account(state_updated_at=utc() - timedelta(minutes=2)), called_from_event=False
        )

    # more than 15 minutes old should become degraded in case of the periodic task
    account = get_account(state_updated_at=utc() - timedelta(minutes=16))
    await repository.create(account)
    await service.configure_discovered_accounts()

    updated_account = await repository.get(account.id)
    assert updated_account
    assert isinstance(updated_account.state, CloudAccountStates.Degraded)

    assert len(domain_sender.events) == 1
    event = domain_sender.events[0]
    assert isinstance(event, AwsAccountDegraded)
    assert event.cloud_account_id == account.id
    assert event.aws_account_id == account_id
    assert event.tenant_id == account.workspace_id


@pytest.mark.asyncio
async def test_handle_cf_sqs_message(
    repository: CloudAccountRepositoryMock, service: CloudAccountServiceImpl, request_handler_mock: RequestHandlerMock
) -> None:
    async def handle_request(_: Request) -> Response:
        return Response(200, content=b"ok")

    def notification(kind: str, physical_resource_id: Optional[str] = None) -> Json:
        base = {
            "RequestType": kind,
            "ServiceToken": "arn:aws:sns:us-east-1:12345:SomeCallbacks",
            "ResponseURL": "https://cloudformation-custom.test.com/",
            "StackId": "arn:aws:cloudformation:us-east-1:12345:stack/name/some-id",
            "RequestId": "855e25d5-3b80-4aed-b9f4-af8682deaf79",
            "LogicalResourceId": "FixAccessFunction",
            "ResourceType": "Custom::Function",
            "ResourceProperties": {
                "ServiceToken": "arn:aws:sns:us-east-1:12345:SomeCallbacks",
                "RoleName": role_name,
                "ExternalId": str(external_id),
                "WorkspaceId": str(test_workspace_id),
                "StackId": "arn:aws:cloudformation:us-east-1:12345:stack/name/some-id",
            },
        }
        if physical_resource_id:
            base["PhysicalResourceId"] = physical_resource_id
        return {"Body": json.dumps(base)}

    # Handle Create Message
    request_handler_mock.append(handle_request)
    assert len(repository.accounts) == 0
    account = await service.process_cf_stack_event(notification("Create"))
    assert account is not None
    assert len(repository.accounts) == 1
    assert repository.accounts[account.id] == account

    # Handle Delete Message
    repository.accounts[account.id] = evolve(
        account, state=CloudAccountStates.Configured(AwsCloudAccess(external_id, role_name), enabled=True)
    )
    account = await service.process_cf_stack_event(notification("Delete", str(account.id)))
    assert account is not None
    assert isinstance(account.state, CloudAccountStates.Degraded)
