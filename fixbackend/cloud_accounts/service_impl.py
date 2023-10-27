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
import uuid
from datetime import timedelta, datetime
from hmac import compare_digest
from logging import getLogger
from typing import Any, List, Optional

from attrs import evolve
from fixcloudutils.redis.event_stream import Json, MessageContext, RedisStreamListener
from fixcloudutils.redis.pub_sub import RedisPubSubPublisher
from fixcloudutils.service import Service
from redis.asyncio import Redis

from fixbackend.cloud_accounts.last_scan_repository import LastScanRepository
from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount, LastScanAccountInfo, LastScanInfo
from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.cloud_accounts.service import CloudAccountService, WrongExternalId
from fixbackend.config import Config
from fixbackend.domain_events import DomainEventsStreamName
from fixbackend.domain_events.events import (
    AwsAccountDeleted,
    AwsAccountDiscovered,
    TenantAccountsCollected,
    AwsAccountConfigured,
)
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.errors import AccessDenied
from fixbackend.ids import CloudAccountId, ExternalId, FixCloudAccountId, WorkspaceId
from fixbackend.workspaces.repository import WorkspaceRepository
from fixbackend.cloud_accounts.account_setup import AwsAccountSetupHelper

log = getLogger(__name__)


class CloudAccountServiceImpl(CloudAccountService, Service):
    def __init__(
        self,
        workspace_repository: WorkspaceRepository,
        cloud_account_repository: CloudAccountRepository,
        pubsub_publisher: RedisPubSubPublisher,
        domain_event_publisher: DomainEventPublisher,
        last_scan_repo: LastScanRepository,
        readwrite_redis: Redis,
        config: Config,
        account_setup_helper: AwsAccountSetupHelper,
        account_setup_sleep_seconds: float = 30,
    ) -> None:
        self.workspace_repository = workspace_repository
        self.cloud_account_repository = cloud_account_repository
        self.pubsub_publisher = pubsub_publisher
        self.domain_events = domain_event_publisher

        self.last_scan_repo = last_scan_repo
        self.domain_event_listener = RedisStreamListener(
            readwrite_redis,
            DomainEventsStreamName,
            group="fixbackent-cloudaccountservice-domain",
            listener=config.instance_id,
            message_processor=self.process_domain_event,
            consider_failed_after=timedelta(minutes=5),
            batch_size=1,
        )
        self.instance_id = config.instance_id
        self.cloud_account_setup_timeout = timedelta(minutes=15)
        self.cloud_account_setup_listener = RedisStreamListener(
            readwrite_redis,
            DomainEventsStreamName,
            group="fixbackent-cloudaccountservice-accountsetup",
            listener=config.instance_id,
            message_processor=self.process_domain_event,
            consider_failed_after=self.cloud_account_setup_timeout,  # try setup an account for 15 minutes and give up
            batch_size=1,
            parallelism=1000,
        )
        self.account_setup_helper = account_setup_helper
        self.account_setup_sleep_seconds = account_setup_sleep_seconds

    async def start(self) -> Any:
        return await self.domain_event_listener.start()

    async def stop(self) -> Any:
        return await self.domain_event_listener.stop()

    async def process_domain_event(self, message: Json, context: MessageContext) -> None:
        match context.kind:
            case TenantAccountsCollected.kind:
                event = TenantAccountsCollected.from_json(message)
                await self.last_scan_repo.set_last_scan(
                    event.tenant_id,
                    LastScanInfo(
                        {
                            account_id: LastScanAccountInfo(
                                account.account_id,
                                account.duration_seconds,
                                account.scanned_resources,
                                account.started_at,
                            )
                            for account_id, account in event.cloud_accounts.items()
                        },
                        event.next_run,
                    ),
                )

            case AwsAccountConfigured.kind:
                configured_event = AwsAccountConfigured.from_json(message)
                account = await self.cloud_account_repository.get(configured_event.cloud_account_id)
                if account is None:
                    log.warning(f"Account {configured_event.cloud_account_id} not found, cannot mark as configured")
                    return None
                await self.cloud_account_repository.update(account.id, evolve(account, is_configured=True))

            case _:
                pass  # ignore other domain events

    async def process_cloud_account_discovered(self, message: Json, context: MessageContext) -> None:
        match context.kind:
            case AwsAccountDiscovered.kind:
                event = AwsAccountDiscovered.from_json(message)
                await self.wait_for_account_setup(event.cloud_account_id)

            case _:
                pass

    async def wait_for_account_setup(self, cloud_account_id: FixCloudAccountId) -> None:
        account = await self.cloud_account_repository.get(cloud_account_id)
        if account is None:
            log.warning(f"Account {cloud_account_id} not found, cannot setup account")
            return None

        started = datetime.utcnow()

        if not isinstance(account.access, AwsCloudAccess):
            raise ValueError(f"Account {cloud_account_id} has unknown access type {type(account.access)}")

        while datetime.utcnow() - started < self.cloud_account_setup_timeout:
            if await self.account_setup_helper.can_assume_role(account.access.aws_account_id, account.access.role_name):
                await self.domain_events.publish(
                    AwsAccountConfigured(
                        cloud_account_id=cloud_account_id,
                        tenant_id=account.workspace_id,
                        aws_account_id=account.access.aws_account_id,
                    )
                )
                return None
            else:
                log.info(f"Account {cloud_account_id} not setup yet, waiting")
                await asyncio.sleep(self.account_setup_sleep_seconds)

        raise TimeoutError(f"Account {cloud_account_id} not setup after {self.cloud_account_setup_timeout}, giving up")

    async def create_aws_account(
        self, workspace_id: WorkspaceId, account_id: CloudAccountId, role_name: str, external_id: ExternalId
    ) -> CloudAccount:
        """Create a cloud account."""

        organization = await self.workspace_repository.get_workspace(workspace_id)
        if organization is None:
            raise ValueError("Organization does not exist")
        if not compare_digest(str(organization.external_id), str(external_id)):
            raise WrongExternalId("External ids does not match")

        async def account_already_exists(workspace_id: WorkspaceId, account_id: str) -> Optional[CloudAccount]:
            accounts = await self.cloud_account_repository.list_by_workspace_id(workspace_id)
            maybe_account = next(
                iter(
                    [
                        account
                        for account in accounts
                        if isinstance(account.access, AwsCloudAccess) and account.access.aws_account_id == account_id
                    ]
                ),
                None,
            )
            return maybe_account

        account = CloudAccount(
            id=FixCloudAccountId(uuid.uuid4()),
            workspace_id=workspace_id,
            access=AwsCloudAccess(aws_account_id=account_id, external_id=external_id, role_name=role_name),
            name=None,
            is_configured=False,
            enabled=True,
        )
        if existing := await account_already_exists(workspace_id, account_id):
            account = evolve(account, id=existing.id)
            result = await self.cloud_account_repository.update(existing.id, account)
        else:
            result = await self.cloud_account_repository.create(account)

        message = {
            "cloud_account_id": str(result.id),
            "workspace_id": str(result.workspace_id),
            "aws_account_id": account_id,
        }
        await self.pubsub_publisher.publish(
            kind="cloud_account_created", message=message, channel=f"tenant-events::{workspace_id}"
        )
        await self.domain_events.publish(
            AwsAccountDiscovered(cloud_account_id=result.id, tenant_id=workspace_id, aws_account_id=account_id)
        )
        return result

    async def delete_cloud_account(self, cloud_account_id: FixCloudAccountId, workspace_id: WorkspaceId) -> None:
        account = await self.cloud_account_repository.get(cloud_account_id)
        if account is None:
            return None  # account already deleted, do nothing
        if account.workspace_id != workspace_id:
            raise AccessDenied("Deletion of cloud accounts is only allowed by the owning organization.")

        await self.cloud_account_repository.delete(cloud_account_id)
        match account.access:
            case AwsCloudAccess(account_id, _, _):
                await self.domain_events.publish(AwsAccountDeleted(cloud_account_id, workspace_id, account_id))
            case _:
                pass

    async def last_scan(self, workspace_id: WorkspaceId) -> Optional[LastScanInfo]:
        return await self.last_scan_repo.get_last_scan(workspace_id)

    async def get_cloud_account(
        self, cloud_account_id: FixCloudAccountId, workspace_id: WorkspaceId
    ) -> Optional[CloudAccount]:
        account = await self.cloud_account_repository.get(cloud_account_id)

        if account is None:
            return None

        if account.workspace_id != workspace_id:
            raise AccessDenied("This account does not belong to this workspace.")

        return account

    async def list_accounts(self, workspace_id: WorkspaceId) -> List[CloudAccount]:
        return await self.cloud_account_repository.list_by_workspace_id(workspace_id)

    async def update_cloud_account(
        self,
        workspace_id: WorkspaceId,
        cloud_account_id: FixCloudAccountId,
        name: str,
    ) -> CloudAccount:
        old_account = await self.cloud_account_repository.get(cloud_account_id)
        if old_account is None:
            raise ValueError(f"Cloud account {cloud_account_id} not found")

        if old_account.workspace_id != workspace_id:
            raise AccessDenied("This account does not belong to this workspace.")

        new_account = evolve(old_account, name=name)

        return await self.cloud_account_repository.update(cloud_account_id, new_account)
