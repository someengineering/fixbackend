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
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, cast

from fixcloudutils.asyncio.periodic import Periodic
from fixcloudutils.redis.event_stream import Json, MessageContext, RedisStreamListener
from fixcloudutils.service import Service
from fixcloudutils.util import parse_utc_str, utc
from redis.asyncio import Redis

from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount
from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.collect.collect_queue import AccountInformation, AwsAccountInformation, CollectQueue
from fixbackend.dispatcher.collect_progress import AccountCollectProgress
from fixbackend.dispatcher.next_run_repository import NextRunRepository
from fixbackend.domain_events.events import (
    TenantAccountsCollected,
    WorkspaceCreated,
    AwsAccountDiscovered,
    CloudAccountCollectInfo,
)
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import CloudAccountId, WorkspaceId
from fixbackend.metering import MeteringRecord
from fixbackend.metering.metering_repository import MeteringRepository
from uuid import UUID

log = logging.getLogger(__name__)


class DispatcherService(Service):
    def __init__(
        self,
        readwrite_redis: Redis,
        cloud_account_repo: CloudAccountRepository,
        next_run_repo: NextRunRepository,
        metering_repo: MeteringRepository,
        collect_queue: CollectQueue,
        access_manager: GraphDatabaseAccessManager,
        domain_event_sender: DomainEventPublisher,
        temp_store_redis: Redis,
        domain_events_stream_name: str,
    ) -> None:
        self.cloud_account_repo = cloud_account_repo
        self.next_run_repo = next_run_repo
        self.metering_repo = metering_repo
        self.collect_queue = collect_queue
        self.access_manager = access_manager
        self.periodic = Periodic("schedule_next_runs", self.schedule_next_runs, timedelta(minutes=1))
        self.domain_event_listener = RedisStreamListener(
            readwrite_redis,
            domain_events_stream_name,
            group="dispatching",
            listener="dispatching",
            message_processor=self.process_domain_event,
            consider_failed_after=timedelta(minutes=5),
            batch_size=1,
        )
        self.collect_result_listener = RedisStreamListener(
            readwrite_redis,
            "collect-events",
            group="dispatching",
            listener="dispatching",
            message_processor=self.process_collect_done_message,
            consider_failed_after=timedelta(minutes=5),
            batch_size=1,
        )
        self.temp_store_redis = temp_store_redis
        self.domain_event_sender = domain_event_sender

    async def start(self) -> Any:
        await self.collect_result_listener.start()
        await self.domain_event_listener.start()
        await self.periodic.start()

    async def stop(self) -> None:
        await self.periodic.stop()
        await self.domain_event_listener.stop()
        await self.collect_result_listener.stop()

    async def process_domain_event(self, message: Json, context: MessageContext) -> None:
        match context.kind:
            case WorkspaceCreated.kind:
                wc_event = WorkspaceCreated.from_json(message)
                await self.workspace_created(wc_event.workspace_id)

            case AwsAccountDiscovered.kind:
                awd_event = AwsAccountDiscovered.from_json(message)
                await self.cloud_account_created(awd_event.cloud_account_id)

            case _:
                pass  # ignore other domain events

    async def process_collect_done_message(self, message: Json, context: MessageContext) -> None:
        match context.kind:
            case "collect-done":
                await self.collect_job_finished(message)
            case _:
                log.info(f"Collect messages: will ignore messages of kine {context.kind}")

    def _collect_progress_hash_key(self, workspace_id: WorkspaceId) -> str:
        return f"dispatching:collect_jobs_in_progress:{workspace_id}"

    async def complete_collect_job(
        self, tenant_id: WorkspaceId, collected_accounts: Dict[CloudAccountId, MeteringRecord]
    ) -> None:
        redis_set_key = self._collect_progress_hash_key(tenant_id)

        async def get_redis_hash() -> Dict[bytes, bytes]:
            result = await self.temp_store_redis.hgetall(redis_set_key)  # type: ignore
            return cast(Dict[bytes, bytes], result)

        def parse_collect_state(hash: Dict[bytes, bytes]) -> Dict[CloudAccountId, AccountCollectProgress]:
            return {
                CloudAccountId(UUID(hex=k.decode())): AccountCollectProgress.from_json_bytes(v) for k, v in hash.items()
            }

        async def mark_as_done(
            collect_state: Dict[CloudAccountId, AccountCollectProgress]
        ) -> Dict[CloudAccountId, AccountCollectProgress]:
            completed = {}
            for done_id, record in collected_accounts.items():
                if done_id not in collect_state:
                    log.error(f"Could not find collect job context for accound id {done_id}")
                    continue
                completed[done_id] = collect_state[done_id].done(
                    scanned_resources=record.nr_of_resources_collected, scan_duration=record.duration
                )
            redis_mapping = {str(k): v.to_json_str() for k, v in completed.items()}
            if redis_mapping:
                await self.temp_store_redis.hset(redis_set_key, mapping=redis_mapping)  # type: ignore
            return collect_state | completed

        def all_jobs_finished(collect_state: Dict[CloudAccountId, AccountCollectProgress]) -> bool:
            return all(job.is_done() for job in collect_state.values())

        async def send_domain_event(collect_state: Dict[CloudAccountId, AccountCollectProgress]) -> None:
            collected_accounts = {
                k: CloudAccountCollectInfo(v.collection_done.scanned_resources, v.collection_done.duration_seconds)
                for k, v in collect_state.items()
                if v.collection_done
            }
            next_run = await self.next_run_repo.get(tenant_id)
            event = TenantAccountsCollected(tenant_id, collected_accounts, next_run)
            await self.domain_event_sender.publish(event)

        # fetch the redis hash
        hash = await get_redis_hash()
        if not hash:
            log.error(f"Could not find any job context for tenant id {tenant_id}")
            return
        # parse it to dataclass
        tenant_collect_state = parse_collect_state(hash)
        # mark the job as done
        tenant_collect_state = await mark_as_done(tenant_collect_state)
        # check if we can send the domain event
        if not all_jobs_finished(tenant_collect_state):
            return

        # all jobs are finished, send domain event and delete the hash
        await send_domain_event(tenant_collect_state)
        await self.temp_store_redis.delete(redis_set_key)

    async def collect_job_finished(self, message: Json) -> None:
        job_id = message["job_id"]
        task_id = message["task_id"]
        workspace_id = WorkspaceId(uuid.UUID(message["tenant_id"]))
        account_info: Dict[str, Any] = message["account_info"]
        messages = message["messages"]
        started_at = parse_utc_str(message["started_at"])
        duration = message["duration"]
        records = [
            MeteringRecord(
                id=uuid.uuid4(),
                workspace_id=workspace_id,
                cloud=account_details["cloud"],
                account_id=account_id,
                account_name=account_details["name"],
                timestamp=utc(),
                job_id=job_id,
                task_id=task_id,
                nr_of_resources_collected=sum(account_details["summary"].values()),
                nr_of_error_messages=len(messages),
                started_at=started_at,
                duration=duration,
            )
            for account_id, account_details in account_info.items()
        ]
        collected_accounts = {CloudAccountId(UUID(record.account_id)): record for record in records}
        await self.metering_repo.add(records)
        await self.complete_collect_job(
            workspace_id,
            collected_accounts,
        )

    async def workspace_created(self, workspace_id: WorkspaceId) -> None:
        # store an entry in the next_run table
        next_run_at = await self.compute_next_run(workspace_id)
        await self.next_run_repo.create(workspace_id, next_run_at)

    async def cloud_account_created(self, cloud_account_id: CloudAccountId) -> None:
        if account := await self.cloud_account_repo.get(cloud_account_id):
            await self.trigger_collect(account)
        else:
            log.error("Received a message, that a cloud account is created, but it does not exist in the database")

    async def compute_next_run(self, tenant: WorkspaceId, last_run: Optional[datetime] = None) -> datetime:
        now = utc()
        delta = timedelta(hours=1)  # TODO: compute delta dependent on the tenant.
        initial_time = last_run or now
        diff = now - initial_time
        if diff.total_seconds() > 0:  # if the last run is in the past, make sure the next run is in the future
            periods = (diff // delta) + 1
            result = initial_time + (delta * periods)
        else:  # next run is already in the future. compute offset.
            result = initial_time + delta
        log.info(f"Next run for tenant: {tenant} is {result}")
        return result

    async def _add_collect_in_progress_account(self, workspace_id: WorkspaceId, account_id: CloudAccountId) -> None:
        value = AccountCollectProgress(account_id, utc()).to_json_str()
        await self.temp_store_redis.hset(name=self._collect_progress_hash_key(workspace_id), key=str(account_id), value=value)  # type: ignore # noqa
        # cleanup after 4 hours just to be sure
        await self.temp_store_redis.expire(name=self._collect_progress_hash_key(workspace_id), time=timedelta(hours=4))

    async def account_collect_in_progress(self, workspace_id: WorkspaceId, cloud_account_id: CloudAccountId) -> bool:
        ongoing_collect = await self.temp_store_redis.hget(self._collect_progress_hash_key(workspace_id), str(cloud_account_id))  # type: ignore # noqa
        return ongoing_collect is not None

    async def trigger_collect(self, account: CloudAccount) -> None:
        if await self.account_collect_in_progress(account.workspace_id, account.id):
            log.info(f"Collect for tenant: {account.workspace_id} and account: {account.id} is already in progress.")
            return

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

        if (ai := account_information()) and (
            db := await self.access_manager.get_database_access(account.workspace_id)
        ):
            job_id = str(uuid.uuid4())
            log.info(
                f"Trigger collect for tenant: {account.workspace_id} and account: {account.id} with job_id: {job_id}"
            )
            await self._add_collect_in_progress_account(account.workspace_id, account.id)
            await self.collect_queue.enqueue(db, ai, job_id=job_id)

    async def schedule_next_runs(self) -> None:
        now = utc()

        async for workspace_id, at in self.next_run_repo.older_than(now):
            if accounts := await self.cloud_account_repo.list_by_workspace_id(workspace_id):
                for account in accounts:
                    await self.trigger_collect(account)
                next_run_at = await self.compute_next_run(workspace_id, at)
                await self.next_run_repo.update_next_run_at(workspace_id, next_run_at)
            else:
                log.error("Received a message, that a cloud account is created, but it does not exist in the database")
                continue
