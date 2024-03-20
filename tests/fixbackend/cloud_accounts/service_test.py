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
import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, override

import boto3
import pytest
from attrs import evolve
from fixcloudutils.redis.event_stream import MessageContext
from fixcloudutils.types import Json
from fixcloudutils.util import utc
from httpx import AsyncClient, Request, Response
from redis.asyncio import Redis
from fixbackend.workspaces.repository import WorkspaceRepository
from fixbackend.workspaces.models import Workspace

from fixbackend.analytics import AnalyticsEventSender
from fixbackend.auth.models import User
from fixbackend.cloud_accounts.account_setup import AssumeRoleResult, AssumeRoleResults, AwsAccountSetupHelper
from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount, CloudAccountStates
from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.cloud_accounts.service_impl import CloudAccountServiceImpl
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.config import Config
from fixbackend.domain_events.events import (
    AwsAccountConfigured,
    AwsAccountDegraded,
    AwsAccountDiscovered,
    CloudAccountCollectInfo,
    CloudAccountNameChanged,
    Event,
    TenantAccountsCollected,
)
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.errors import NotAllowed, ResourceNotFound
from fixbackend.ids import (
    AwsRoleName,
    CloudAccountAlias,
    CloudAccountId,
    CloudAccountName,
    CloudNames,
    ExternalId,
    FixCloudAccountId,
    ProductTier,
    TaskId,
    UserCloudAccountName,
    WorkspaceId,
)
from fixbackend.notification.email.email_messages import EmailMessage
from fixbackend.notification.notification_service import NotificationService
from tests.fixbackend.conftest import RequestHandlerMock, RedisPubSubPublisherMock


account_id = CloudAccountId("foobar")
role_name = AwsRoleName("FooBarRole")
account_name = CloudAccountName("foobar-account-name")
user_account_name = UserCloudAccountName("foobar-user-account-name")
account_alias = CloudAccountAlias("foobar-account-alias")
task_id = TaskId("task_id")


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
            return AssumeRoleResults.Success("foo", "bar", "baz", utc())
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


class InMemoryNotificationService(NotificationService):
    # noinspection PyMissingConstructor
    def __init__(self) -> None:
        self.notified_workspaces: List[WorkspaceId] = []

    @override
    async def send_message_to_workspace(self, *, workspace_id: WorkspaceId, message: EmailMessage) -> None:
        self.notified_workspaces.append(workspace_id)


@pytest.fixture
def notification_service() -> InMemoryNotificationService:
    return InMemoryNotificationService()


now = utc()


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
    workspace_repository: WorkspaceRepository,
    cloud_account_repository: CloudAccountRepository,
    pubsub_publisher: RedisPubSubPublisherMock,
    domain_sender: DomainEventSenderMock,
    account_setup_helper: AwsAccountSetupHelperMock,
    arq_redis: Redis,
    default_config: Config,
    boto_session: boto3.Session,
    http_client: AsyncClient,
    notification_service: InMemoryNotificationService,
    analytics_event_sender: AnalyticsEventSender,
) -> CloudAccountServiceImpl:
    return CloudAccountServiceImpl(
        workspace_repository=workspace_repository,
        cloud_account_repository=cloud_account_repository,
        pubsub_publisher=pubsub_publisher,
        domain_event_publisher=domain_sender,
        readwrite_redis=arq_redis,
        config=default_config,
        account_setup_helper=account_setup_helper,
        dispatching=False,
        boto_session=boto_session,
        http_client=http_client,
        cf_stack_queue_url=None,
        notification_service=notification_service,
        analytics_event_sender=analytics_event_sender,
    )


@pytest.mark.asyncio
async def test_create_aws_account(
    cloud_account_repository: CloudAccountRepository,
    domain_sender: DomainEventSenderMock,
    service: CloudAccountServiceImpl,
    user: User,
    workspace: Workspace,
    workspace_repository: WorkspaceRepository,
    subscription: AwsMarketplaceSubscription,
) -> None:
    # happy case
    acc = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=account_id,
        role_name=role_name,
        external_id=workspace.external_id,
        account_name=account_name,
    )
    assert await cloud_account_repository.count_by_workspace_id(workspace.id) == 1
    account = await cloud_account_repository.get(acc.id)
    assert account is not None
    assert account.workspace_id == workspace.id
    assert account.account_id == account_id
    assert account.account_name == account_name
    state = account.state
    assert isinstance(state, CloudAccountStates.Discovered)
    assert state.enabled is True
    access = state.access
    assert isinstance(access, AwsCloudAccess)
    assert access.role_name == role_name
    assert access.external_id == workspace.external_id

    assert len(domain_sender.events) == 1
    event = domain_sender.events[0]
    assert isinstance(event, AwsAccountDiscovered)
    assert event.cloud_account_id == acc.id
    assert event.aws_account_id == account_id
    assert event.tenant_id == acc.workspace_id

    # reaching the account limit of the free tier, expext a Discovered account with enabled=False
    previous_tier = workspace.product_tier
    await workspace_repository.update_subscription(workspace.id, subscription.id)
    await workspace_repository.update_product_tier(workspace.id, ProductTier.Free)
    new_account = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=CloudAccountId("new_one"),
        role_name=role_name,
        external_id=workspace.external_id,
        account_name=CloudAccountName("new_account_name"),
    )
    assert new_account is not None
    state = new_account.state
    assert isinstance(state, CloudAccountStates.Discovered)
    assert state.enabled is False
    # the disabled account should be shown in all discovered:
    all_discovered = await cloud_account_repository.list_all_discovered_accounts()
    assert len(all_discovered) == 2
    # cleanup
    await cloud_account_repository.delete(new_account.id)
    await workspace_repository.update_product_tier(workspace.id, previous_tier)

    # account already exists, account_name should be updated, but nothing else
    domain_sender.events = []
    idempotent_account = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=account_id,
        role_name=None,
        external_id=workspace.external_id,
        account_name=account_name,
    )
    # no extra account should be created
    assert await cloud_account_repository.count_by_workspace_id(workspace.id) == 1
    # domain event should not be published
    assert len(domain_sender.events) == 0
    assert idempotent_account == acc

    # account already exists, account_name should be updated, but nothing else
    domain_sender.events = []
    with_updated_name = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=account_id,
        role_name=None,
        external_id=workspace.external_id,
        account_name=CloudAccountName("foobar"),
    )
    assert await cloud_account_repository.count_by_workspace_id(workspace.id) == 1
    # name has changed: domain event should be published
    assert len(domain_sender.events) == 1
    assert isinstance(domain_sender.events[0], CloudAccountNameChanged)
    assert with_updated_name.workspace_id == acc.workspace_id
    assert with_updated_name.state == acc.state
    assert with_updated_name.account_name == CloudAccountName("foobar")
    assert with_updated_name.user_account_name == acc.user_account_name
    assert with_updated_name.id == acc.id
    assert with_updated_name.account_alias == acc.account_alias

    # account with role_name=None should end up as detected not create any events
    domain_sender.events = []
    detected_account_id = CloudAccountId("foobar2")
    detected_account = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=detected_account_id,
        role_name=None,
        external_id=workspace.external_id,
        account_name=account_name,
    )
    assert detected_account.state == CloudAccountStates.Detected()
    # a new account should be created
    assert await cloud_account_repository.count_by_workspace_id(workspace.id) == 2
    # domain event should not be published
    assert len(domain_sender.events) == 0

    # deleted account can be moved to discovered when re-created
    domain_sender.events = []
    deleted_account_id = CloudAccountId("foobar3")
    deleted_account = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=deleted_account_id,
        role_name=role_name,
        external_id=workspace.external_id,
        account_name=account_name,
    )
    assert len(domain_sender.events) == 1
    await service.delete_cloud_account(user.id, deleted_account.id, workspace.id)
    deleted_account = await service.get_cloud_account(deleted_account.id, workspace.id)
    assert deleted_account.state == CloudAccountStates.Deleted()
    # a new account should be created
    assert await cloud_account_repository.count_by_workspace_id(workspace.id) == 3
    # domain event should be published
    assert len(domain_sender.events) == 2

    # wrong external id
    with pytest.raises(Exception):
        await service.create_aws_account(
            workspace_id=workspace.id,
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
            external_id=workspace.external_id,
            account_name=None,
        )


@pytest.mark.asyncio
async def test_delete_aws_account(
    cloud_account_repository: CloudAccountRepository, service: CloudAccountServiceImpl, user: User, workspace: Workspace
) -> None:
    account = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=account_id,
        role_name=role_name,
        external_id=workspace.external_id,
        account_name=None,
    )
    assert await cloud_account_repository.count_by_workspace_id(workspace.id) == 1

    # deleting someone's else account
    with pytest.raises(Exception):
        await service.delete_cloud_account(user.id, account.id, WorkspaceId(uuid.uuid4()))
    assert await cloud_account_repository.count_by_workspace_id(workspace.id) == 1

    # success
    await service.delete_cloud_account(user.id, account.id, workspace.id)
    accounts = await cloud_account_repository.list_by_workspace_id(workspace.id)
    assert len(accounts) == 1
    assert isinstance(accounts[0].state, CloudAccountStates.Deleted)

    await asyncio.sleep(1.1)

    # when created again, created_at should be updated
    recreated_account = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=account_id,
        role_name=role_name,
        external_id=workspace.external_id,
        account_name=None,
    )
    assert recreated_account.created_at > account.created_at


@pytest.mark.asyncio
async def test_store_last_run_info(
    service: CloudAccountServiceImpl, notification_service: InMemoryNotificationService, workspace: Workspace
) -> None:
    now_without_micros = now.replace(microsecond=0)
    account = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=account_id,
        role_name=role_name,
        external_id=workspace.external_id,
        account_name=None,
    )

    cloud_account_id = account.id
    event = TenantAccountsCollected(
        workspace.id,
        {cloud_account_id: CloudAccountCollectInfo(account_id, 100, 10, now_without_micros, task_id)},
        now_without_micros,
    )
    await service.process_domain_event(
        event.to_json(),
        MessageContext(
            id="test",
            kind=TenantAccountsCollected.kind,
            publisher="test",
            sent_at=now_without_micros,
            received_at=now_without_micros,
        ),
    )

    assert len(notification_service.notified_workspaces) == 1
    assert notification_service.notified_workspaces[0] == workspace.id

    account = await service.get_cloud_account(cloud_account_id, workspace.id)

    assert account.next_scan == now_without_micros
    assert account.account_id == account_id
    assert account.last_scan_duration_seconds == 10
    assert account.last_scan_resources_scanned == 100
    assert account.last_scan_started_at == now_without_micros


@pytest.mark.asyncio
async def test_get_cloud_account(
    cloud_account_repository: CloudAccountRepository, service: CloudAccountServiceImpl, workspace: Workspace
) -> None:
    account = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=account_id,
        role_name=role_name,
        external_id=workspace.external_id,
        account_name=account_name,
    )
    assert await cloud_account_repository.count_by_workspace_id(workspace.id) == 1

    # success
    cloud_account = await service.get_cloud_account(account.id, workspace.id)
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
    with pytest.raises(NotAllowed):
        await service.get_cloud_account(account.id, WorkspaceId(uuid.uuid4()))

    # wrong account id
    with pytest.raises(ResourceNotFound):
        await service.get_cloud_account(FixCloudAccountId(uuid.uuid4()), workspace.id)


@pytest.mark.asyncio
async def test_list_cloud_accounts(
    cloud_account_repository: CloudAccountRepository, service: CloudAccountServiceImpl, workspace: Workspace
) -> None:
    account = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=account_id,
        role_name=role_name,
        external_id=workspace.external_id,
        account_name=None,
    )
    assert await cloud_account_repository.count_by_workspace_id(workspace.id) == 1

    # success
    cloud_accounts = await service.list_accounts(workspace.id)
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
    cloud_account_repository: CloudAccountRepository, service: CloudAccountServiceImpl, workspace: Workspace
) -> None:
    account = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=account_id,
        role_name=role_name,
        external_id=workspace.external_id,
        account_name=account_name,
    )
    assert await cloud_account_repository.count_by_workspace_id(workspace.id) == 1

    # success
    updated = await service.update_cloud_account_name(workspace.id, account.id, user_account_name)
    assert updated.user_account_name == user_account_name
    assert updated.account_name == account_name
    assert updated.account_alias is None
    assert updated.id == account.id
    assert updated.state == account.state
    assert updated.workspace_id == account.workspace_id

    # set name to None
    updated = await service.update_cloud_account_name(workspace.id, account.id, None)
    assert updated.user_account_name is None
    assert updated.account_name == account_name
    assert updated.id == account.id
    assert updated.state == account.state
    assert updated.workspace_id == account.workspace_id

    # wrong tenant id
    with pytest.raises(NotAllowed):
        await service.update_cloud_account_name(WorkspaceId(uuid.uuid4()), account.id, user_account_name)

    # wrong account id
    with pytest.raises(ResourceNotFound):
        await service.update_cloud_account_name(workspace.id, FixCloudAccountId(uuid.uuid4()), user_account_name)


@pytest.mark.asyncio
async def test_handle_account_discovered_success(
    cloud_account_repository: CloudAccountRepository,
    domain_sender: DomainEventSenderMock,
    service: CloudAccountServiceImpl,
    pubsub_publisher: RedisPubSubPublisherMock,
    workspace: Workspace,
) -> None:
    # allowed to perform describe regions
    account = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=account_id,
        role_name=role_name,
        external_id=workspace.external_id,
        account_name=None,
    )
    assert await cloud_account_repository.count_by_workspace_id(workspace.id) == 1

    assert len(domain_sender.events) == 1
    event = domain_sender.events[0]
    assert isinstance(event, AwsAccountDiscovered)

    # happy case, boto3 can assume role
    await service.process_domain_event(event.to_json(), MessageContext("test", event.kind, "test", utc(), utc()))

    message = {
        "cloud_account_id": str(account.id),
        "aws_account_id": account_id,
    }

    assert pubsub_publisher.last_message is not None
    assert pubsub_publisher.last_message[0] == "aws_account_discovered"
    assert pubsub_publisher.last_message[1] == message
    assert pubsub_publisher.last_message[2] == f"tenant-events::{workspace.id}"

    assert len(domain_sender.events) == 2
    event = domain_sender.events[1]
    assert isinstance(event, AwsAccountConfigured)
    assert event.cloud_account_id == account.id
    assert event.aws_account_id == account_id
    assert event.tenant_id == account.workspace_id


@pytest.mark.asyncio
async def test_handle_account_discovered_assume_role_success(
    domain_sender: DomainEventSenderMock,
    service: CloudAccountServiceImpl,
    account_setup_helper: AwsAccountSetupHelperMock,
    workspace: Workspace,
) -> None:
    await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=CloudAccountId("foobar"),
        role_name=AwsRoleName("FooBarRole"),
        external_id=workspace.external_id,
        account_name=None,
    )
    event = domain_sender.events[0]
    account_setup_helper.can_assume = True
    account_setup_helper.can_describe_regions = False
    # boto3 can not describe regions -> fail
    with pytest.raises(Exception):
        await service.process_domain_event(event.to_json(), MessageContext("test", event.kind, "test", utc(), utc()))


@pytest.mark.asyncio
async def test_handle_account_discovered_assume_role_failure(
    cloud_account_repository: CloudAccountRepository,
    domain_sender: DomainEventSenderMock,
    service: CloudAccountServiceImpl,
    account_setup_helper: AwsAccountSetupHelperMock,
    workspace: Workspace,
) -> None:
    # boto3 cannot assume right away
    account_id = CloudAccountId("foobar")
    role_name = AwsRoleName("FooBarRole")
    account = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=account_id,
        role_name=role_name,
        external_id=workspace.external_id,
        account_name=None,
    )
    assert await cloud_account_repository.count_by_workspace_id(workspace.id)
    assert len(domain_sender.events) == 1
    event = domain_sender.events[0]

    account_setup_helper.can_assume = False

    with pytest.raises(Exception):
        await service.process_domain_event(event.to_json(), MessageContext("test", event.kind, "test", utc(), utc()))
    # no event should be published before the account is configured
    assert len(domain_sender.events) == 1

    # now boto3 can assume role and event should be published
    account_setup_helper.can_assume = True
    await service.process_domain_event(event.to_json(), MessageContext("test", event.kind, "test", utc(), utc()))
    assert len(domain_sender.events) == 2
    event = domain_sender.events[1]
    assert isinstance(event, AwsAccountConfigured)
    assert event.cloud_account_id == account.id
    assert event.aws_account_id == account_id
    assert event.tenant_id == account.workspace_id

    after_configured = await service.get_cloud_account(account.id, workspace.id)

    assert after_configured is not None
    assert after_configured.privileged is False
    assert after_configured.state == CloudAccountStates.Configured(
        AwsCloudAccess(workspace.external_id, role_name), enabled=True, scan=True
    )
    assert after_configured.workspace_id == account.workspace_id
    assert after_configured.account_name == account.account_name
    assert after_configured.id == account.id
    assert after_configured.account_id == account.account_id


@pytest.mark.asyncio
async def test_handle_account_discovered_list_accounts_success(
    cloud_account_repository: CloudAccountRepository,
    domain_sender: DomainEventSenderMock,
    service: CloudAccountServiceImpl,
    account_setup_helper: AwsAccountSetupHelperMock,
    workspace: Workspace,
) -> None:
    account_id = CloudAccountId("foobar")
    role_name = AwsRoleName("FooBarRole")
    account = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=account_id,
        role_name=role_name,
        external_id=workspace.external_id,
        account_name=None,
    )
    assert await cloud_account_repository.count_by_workspace_id(workspace.id)
    assert len(domain_sender.events) == 1
    event = domain_sender.events[0]

    account_setup_helper.can_assume = True
    account_setup_helper.org_accounts = {account_id: account_name}

    await service.process_domain_event(event.to_json(), MessageContext("test", event.kind, "test", utc(), utc()))
    assert len(domain_sender.events) == 3
    assert isinstance(domain_sender.events[1], CloudAccountNameChanged)
    assert isinstance(domain_sender.events[2], AwsAccountConfigured)

    after_discovered = await service.get_cloud_account(account.id, workspace.id)

    assert after_discovered is not None
    assert after_discovered.workspace_id == account.workspace_id
    assert after_discovered.account_name == account_name
    assert after_discovered.id == account.id
    assert after_discovered.account_id == account.account_id
    assert after_discovered.privileged is True

    assert after_discovered.state == CloudAccountStates.Configured(
        AwsCloudAccess(workspace.external_id, role_name), enabled=True, scan=True
    )


@pytest.mark.asyncio
async def test_handle_account_discovered_list_aliases_success(
    cloud_account_repository: CloudAccountRepository,
    domain_sender: DomainEventSenderMock,
    service: CloudAccountServiceImpl,
    account_setup_helper: AwsAccountSetupHelperMock,
    workspace: Workspace,
) -> None:
    # boto3 cannot assume right away
    account_id = CloudAccountId("foobar")
    role_name = AwsRoleName("FooBarRole")
    account = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=account_id,
        role_name=role_name,
        external_id=workspace.external_id,
        account_name=None,
    )
    assert await cloud_account_repository.count_by_workspace_id(workspace.id)
    assert len(domain_sender.events) == 1
    event = domain_sender.events[0]

    account_setup_helper.can_assume = True
    account_setup_helper.org_accounts = {}
    account_setup_helper.account_alias = account_alias

    await service.process_domain_event(event.to_json(), MessageContext("test", event.kind, "test", utc(), utc()))
    assert len(domain_sender.events) == 2
    event = domain_sender.events[1]
    assert isinstance(event, AwsAccountConfigured)

    after_discovered = await service.get_cloud_account(account.id, workspace.id)

    assert after_discovered is not None
    assert after_discovered.workspace_id == account.workspace_id
    assert after_discovered.account_name is None
    assert after_discovered.account_alias == account_alias
    assert after_discovered.id == account.id
    assert after_discovered.account_id == account.account_id
    assert after_discovered.privileged is False
    assert after_discovered.state == CloudAccountStates.Configured(
        AwsCloudAccess(workspace.external_id, role_name), enabled=True, scan=True
    )


@pytest.mark.asyncio
async def test_enable_disable_cloud_account(
    cloud_account_repository: CloudAccountRepository,
    service: CloudAccountServiceImpl,
    workspace: Workspace,
    workspace_repository: WorkspaceRepository,
    subscription: AwsMarketplaceSubscription,
) -> None:
    account = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=account_id,
        role_name=role_name,
        external_id=workspace.external_id,
        account_name=None,
    )
    assert await cloud_account_repository.count_by_workspace_id(workspace.id) == 1

    # account is not configured, cannot be enabled
    with pytest.raises(Exception):
        await service.update_cloud_account_enabled(WorkspaceId(uuid.uuid4()), account.id, enabled=True)

    await cloud_account_repository.update(
        account.id,
        lambda account: evolve(
            account,
            state=CloudAccountStates.Configured(
                AwsCloudAccess(workspace.external_id, role_name), enabled=False, scan=False
            ),
            privileged=False,
        ),
    )

    # success
    updated = await service.update_cloud_account_enabled(workspace.id, account.id, enabled=True)
    assert isinstance(updated.state, CloudAccountStates.Configured)
    assert updated.state.access == AwsCloudAccess(workspace.external_id, role_name)
    assert updated.privileged is False
    assert updated.state.enabled is True
    updated_account = await cloud_account_repository.get(account.id)
    assert updated_account
    assert isinstance(updated_account.state, CloudAccountStates.Configured)

    updated = await service.update_cloud_account_enabled(workspace.id, account.id, enabled=False)
    assert isinstance(updated.state, CloudAccountStates.Configured)
    assert updated.state.access == AwsCloudAccess(workspace.external_id, role_name)
    assert updated.privileged is False
    assert updated.state.enabled is False

    # when limit on accounts reached, update is not possible
    await service.update_cloud_account_enabled(workspace.id, account.id, enabled=True)
    await workspace_repository.update_subscription(workspace.id, subscription.id)
    await workspace_repository.update_product_tier(workspace.id, ProductTier.Free)
    new_account = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=CloudAccountId("new_acc"),
        role_name=role_name,
        external_id=workspace.external_id,
        account_name=None,
    )

    await cloud_account_repository.update(
        new_account.id,
        lambda account: evolve(
            account,
            state=CloudAccountStates.Configured(
                AwsCloudAccess(workspace.external_id, role_name), enabled=False, scan=False
            ),
            privileged=False,
        ),
    )

    with pytest.raises(NotAllowed):
        await service.update_cloud_account_enabled(workspace.id, new_account.id, enabled=True)

    await cloud_account_repository.delete(new_account.id)

    # does not work for degraded accounts

    updated_account = await cloud_account_repository.update(
        account.id,
        lambda account: evolve(
            account,
            state=CloudAccountStates.Degraded(AwsCloudAccess(workspace.external_id, role_name), error="test error"),
            privileged=False,
        ),
    )

    with pytest.raises(Exception):
        await service.update_cloud_account_enabled(workspace.id, account.id, enabled=True)

    # wrong tenant id
    with pytest.raises(Exception):
        await service.update_cloud_account_name(WorkspaceId(uuid.uuid4()), account.id, user_account_name)

    # wrong account id
    with pytest.raises(Exception):
        await service.update_cloud_account_name(workspace.id, FixCloudAccountId(uuid.uuid4()), user_account_name)


@pytest.mark.asyncio
async def test_configure_account(
    cloud_account_repository: CloudAccountRepository,
    domain_sender: DomainEventSenderMock,
    service: CloudAccountServiceImpl,
    account_setup_helper: AwsAccountSetupHelperMock,
    workspace: Workspace,
) -> None:
    account_setup_helper.can_assume = False

    def get_account(state_updated_at: datetime, enabled: Optional[bool] = None) -> CloudAccount:
        if enabled is None:
            enabled = True
        return CloudAccount(
            id=FixCloudAccountId(uuid.uuid4()),
            account_id=account_id,
            workspace_id=workspace.id,
            cloud=CloudNames.AWS,
            state=CloudAccountStates.Discovered(AwsCloudAccess(workspace.external_id, role_name), enabled),
            account_name=CloudAccountName("foo"),
            account_alias=CloudAccountAlias("foo_alias"),
            user_account_name=UserCloudAccountName("foo_user"),
            privileged=True,
            last_scan_duration_seconds=10,
            last_scan_resources_scanned=100,
            last_scan_started_at=utc(),
            next_scan=utc(),
            created_at=utc(),
            updated_at=utc(),
            state_updated_at=state_updated_at,
            cf_stack_version=0,
            failed_scan_count=0,
        )

    # fresh account should be retried
    with pytest.raises(Exception):
        await service.configure_account(get_account(state_updated_at=utc()), called_from_event=True)

    with pytest.raises(Exception):
        await service.configure_account(get_account(state_updated_at=utc()), called_from_event=False)

    # if the account is not enabled, account shuold be configured, and disabled for scanning
    account_setup_helper.can_assume = True
    account = get_account(state_updated_at=utc(), enabled=False)
    await cloud_account_repository.create(account)
    result = await service.configure_account(
        account,
        called_from_event=True,
    )
    assert isinstance(result, CloudAccount)

    assert isinstance(result.state, CloudAccountStates.Configured)
    assert result.state.enabled is False
    assert result.state.scan is False
    # cleanup
    await cloud_account_repository.delete(account.id)
    account_setup_helper.can_assume = False
    domain_sender.events = []

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
    await cloud_account_repository.create(account)
    await service.configure_discovered_accounts()

    updated_account = await cloud_account_repository.get(account.id)
    assert updated_account
    assert isinstance(updated_account.state, CloudAccountStates.Degraded)

    assert len(domain_sender.events) == 1
    event = domain_sender.events[0]
    assert isinstance(event, AwsAccountDegraded)
    assert event.cloud_account_id == account.id
    assert event.aws_account_id == account_id
    assert event.tenant_id == account.workspace_id
    assert event.aws_account_name == account.final_name()


@pytest.mark.asyncio
async def test_handle_cf_sqs_message(
    cloud_account_repository: CloudAccountRepository,
    service: CloudAccountServiceImpl,
    request_handler_mock: RequestHandlerMock,
    workspace: Workspace,
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
                "ExternalId": str(workspace.external_id),
                "WorkspaceId": str(workspace.id),
                "StackId": "arn:aws:cloudformation:us-east-1:12345:stack/name/some-id",
            },
        }
        if physical_resource_id:
            base["PhysicalResourceId"] = physical_resource_id
        return {"Body": json.dumps(base)}

    # Handle Create Message
    request_handler_mock.append(handle_request)
    assert await cloud_account_repository.count_by_workspace_id(workspace.id) == 0
    account = await service.process_cf_stack_event(notification("Create"))
    assert account is not None

    assert await cloud_account_repository.count_by_workspace_id(workspace.id) == 1
    repo_account = await cloud_account_repository.get(account.id)
    assert repo_account == account

    # Handle Delete Message
    await cloud_account_repository.update(
        account.id,
        lambda account: evolve(
            account,
            state=CloudAccountStates.Configured(
                AwsCloudAccess(workspace.external_id, role_name), enabled=True, scan=True
            ),
        ),
    )
    account = await service.process_cf_stack_event(notification("Delete", str(account.id)))
    assert account is not None
    assert isinstance(account.state, CloudAccountStates.Degraded)


@pytest.mark.asyncio
async def test_move_to_degraded(
    domain_sender: DomainEventSenderMock, service: CloudAccountServiceImpl, workspace: Workspace
) -> None:

    account = await service.create_aws_account(
        workspace_id=workspace.id,
        account_id=account_id,
        role_name=role_name,
        external_id=workspace.external_id,
        account_name=None,
    )

    cloud_account_id = account.id
    for i in range(4):
        event = TenantAccountsCollected(
            workspace.id,
            {
                cloud_account_id: CloudAccountCollectInfo(
                    account_id, scanned_resources=0, duration_seconds=10, started_at=now, task_id=task_id
                )
            },
            now,
        )
        await service.process_domain_event(
            event.to_json(),
            MessageContext(
                id="test", kind=TenantAccountsCollected.kind, publisher="test", sent_at=now, received_at=now
            ),
        )

    updated_account = await service.get_cloud_account(cloud_account_id, workspace.id)

    assert updated_account
    assert isinstance(updated_account.state, CloudAccountStates.Degraded)

    assert len(domain_sender.events) == 2
    published_event = domain_sender.events[1]
    assert isinstance(published_event, AwsAccountDegraded)
    assert published_event.cloud_account_id == account.id
    assert published_event.aws_account_id == account_id
    assert published_event.tenant_id == account.workspace_id
    assert published_event.error == "Too many consecutive failed scans"
    assert published_event.aws_account_name == account.final_name()
