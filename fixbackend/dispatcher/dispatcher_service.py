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

import logging
from datetime import timedelta, datetime
from typing import Any, Optional

from fixcloudutils.asyncio.periodic import Periodic
from fixcloudutils.redis.event_stream import RedisStreamListener, Json, MessageContext
from fixcloudutils.service import Service
from fixcloudutils.util import utc
from redis.asyncio import Redis

from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount
from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.collect.collect_queue import CollectQueue, AccountInformation, AwsAccountInformation
from fixbackend.dispatcher.next_run_repository import NextRunRepository
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import CloudAccountId, TenantId

log = logging.getLogger(__name__)


class DispatcherService(Service):
    def __init__(
        self,
        readwrite_redis: Redis,
        cloud_account_repo: CloudAccountRepository,
        next_run_repo: NextRunRepository,
        collect_queue: CollectQueue,
        access_manager: GraphDatabaseAccessManager,
    ) -> None:
        self.cloud_account_repo = cloud_account_repo
        self.next_run_repo = next_run_repo
        self.collect_queue = collect_queue
        self.access_manager = access_manager
        self.periodic = Periodic("schedule_next_runs", self.schedule_next_runs, timedelta(minutes=1))
        self.listener = RedisStreamListener(
            readwrite_redis,
            "fixbackend::cloudaccount",
            group="dispatching",
            listener="dispatching",
            message_processor=self.process_message,
            consider_failed_after=timedelta(minutes=5),
            batch_size=1,
        )

    async def start(self) -> Any:
        await self.listener.start()
        await self.periodic.start()

    async def stop(self) -> None:
        await self.periodic.stop()
        await self.listener.stop()

    async def process_message(self, message: Json, context: MessageContext) -> None:
        match context.kind:
            case "cloud_account_created":
                await self.cloud_account_created(CloudAccountId(message["id"]))
            case "cloud_account_deleted":
                await self.cloud_account_deleted(CloudAccountId(message["id"]))
            case _:
                log.error(f"Don't know how to handle messages of kind {context.kind}")

    async def cloud_account_created(self, cid: CloudAccountId) -> None:
        if account := await self.cloud_account_repo.get(cid):
            await self.trigger_collect(account)
            # store an entry in the next_run table
            next_run_at = await self.compute_next_run(account.tenant_id)
            await self.next_run_repo.create(cid, next_run_at)
        else:
            log.error("Received a message, that a cloud account is created, but it does not exist in the database")

    async def cloud_account_deleted(self, cid: CloudAccountId) -> None:
        # delete the entry from the scheduler table
        await self.next_run_repo.delete(cid)

    async def compute_next_run(self, tenant: TenantId) -> datetime:
        # compute next run time dependent on the tenant.
        result = utc() + timedelta(hours=1)
        log.info(f"Next run for tenant: {tenant} is {result}")
        return result

    async def trigger_collect(self, account: CloudAccount) -> None:
        def account_information() -> Optional[AccountInformation]:
            match account.access:
                case AwsCloudAccess(account_id=account_id, role_name=role_name, external_id=external_id):
                    return AwsAccountInformation(
                        aws_account_id=account_id,
                        aws_account_name=None,
                        aws_role_arn=f"arn:aws:iam::{account_id}:role/{role_name}",
                        external_id=str(external_id),
                    )
                case _:
                    log.error(f"Don't know how to handle this cloud access {account.access}. Ignore it.")
                    return None

        if (ai := account_information()) and (db := await self.access_manager.get_database_access(account.tenant_id)):
            await self.collect_queue.enqueue(db, ai)  # TODO: create a unique identifier for this run

    async def schedule_next_runs(self) -> None:
        now = utc()
        async for cid in self.next_run_repo.older_than(now):
            if account := await self.cloud_account_repo.get(cid):
                await self.trigger_collect(account)
                next_run_at = await self.compute_next_run(account.tenant_id)
                await self.next_run_repo.update_next_run_at(cid, next_run_at)
            else:
                log.error("Received a message, that a cloud account is created, but it does not exist in the database")
                continue
