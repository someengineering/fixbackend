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
from hmac import compare_digest
from typing import Any, Optional

from attrs import evolve
from fixcloudutils.redis.event_stream import Json, MessageContext, RedisStreamListener
from fixcloudutils.redis.pub_sub import RedisPubSubPublisher
from fixcloudutils.service import Service
from redis.asyncio import Redis

from fixbackend.cloud_accounts.last_scan_repository import LastScanRepository
from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount, LastScanAccountInfo, LastScanInfo
from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.cloud_accounts.service import CloudAccountService, WrongExternalId
from fixbackend.domain_events import DomainEventsStreamName
from fixbackend.domain_events.events import AwsAccountDeleted, AwsAccountDiscovered, TenantAccountsCollected
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.errors import Unauthorized
from fixbackend.ids import FixCloudAccountId, ExternalId, WorkspaceId, CloudAccountId
from fixbackend.keyvalue.json_kv import JsonStore
from fixbackend.workspaces.repository import WorkspaceRepository


class CloudAccountServiceImpl(CloudAccountService, Service):
    def __init__(
        self,
        workspace_repository: WorkspaceRepository,
        cloud_account_repository: CloudAccountRepository,
        pubsub_publisher: RedisPubSubPublisher,
        domain_event_publisher: DomainEventPublisher,
        kv_store: JsonStore,
        readwrite_redis: Redis,
    ) -> None:
        self.workspace_repository = workspace_repository
        self.cloud_account_repository = cloud_account_repository
        self.pubsub_publisher = pubsub_publisher
        self.domain_events = domain_event_publisher

        self.last_scan_repo = LastScanRepository(kv_store)
        self.domain_event_listener = RedisStreamListener(
            readwrite_redis,
            DomainEventsStreamName,
            group="dispatching",
            listener="dispatching",
            message_processor=self.process_domain_event,
            consider_failed_after=timedelta(minutes=5),
            batch_size=1,
        )

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
                                account.account_id, account.duration_seconds, account.scanned_resources
                            )
                            for account_id, account in event.cloud_accounts.items()
                        },
                        event.next_run,
                    ),
                )

            case _:
                pass  # ignore other domain events

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
                        if isinstance(account.access, AwsCloudAccess) and account.access.account_id == account_id
                    ]
                ),
                None,
            )
            return maybe_account

        account = CloudAccount(
            id=FixCloudAccountId(uuid.uuid4()),
            workspace_id=workspace_id,
            access=AwsCloudAccess(account_id=account_id, external_id=external_id, role_name=role_name),
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
            raise Unauthorized("Deletion of cloud accounts is only allowed by the owning organization.")

        await self.cloud_account_repository.delete(cloud_account_id)
        match account.access:
            case AwsCloudAccess(account_id, _, _):
                await self.domain_events.publish(AwsAccountDeleted(cloud_account_id, workspace_id, account_id))
            case _:
                pass

    async def last_scan(self, workspace_id: WorkspaceId) -> Optional[LastScanInfo]:
        return await self.last_scan_repo.get_last_scan(workspace_id)
