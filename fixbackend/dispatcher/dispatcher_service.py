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
from fixbackend.dispatcher.collect_progress import AccountCollectInProgress
from fixbackend.dispatcher.next_run_repository import NextRunRepository
from fixbackend.domain_events.events import TenantAccountsCollected
from fixbackend.domain_events.sender import DomainEventSender
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import CloudAccountId, WorkspaceId
from fixbackend.metering import MeteringRecord
from fixbackend.metering.metering_repository import MeteringRepository

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
        domain_event_sender: DomainEventSender,
        temp_store_redis: Redis,
    ) -> None:
        self.cloud_account_repo = cloud_account_repo
        self.next_run_repo = next_run_repo
        self.metering_repo = metering_repo
        self.collect_queue = collect_queue
        self.access_manager = access_manager
        self.periodic = Periodic("schedule_next_runs", self.schedule_next_runs, timedelta(minutes=1))
        self.cloudaccount_listener = RedisStreamListener(
            readwrite_redis,
            "fixbackend::cloudaccount",
            group="dispatching",
            listener="dispatching",
            message_processor=self.process_cloud_account_changed_message,
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
        self.domaim_event_sender = domain_event_sender

    async def start(self) -> Any:
        await self.collect_result_listener.start()
        await self.cloudaccount_listener.start()
        await self.periodic.start()

    async def stop(self) -> None:
        await self.periodic.stop()
        await self.cloudaccount_listener.stop()
        await self.collect_result_listener.stop()

    async def process_cloud_account_changed_message(self, message: Json, context: MessageContext) -> None:
        match context.kind:
            case "cloud_account_created":
                await self.cloud_account_created(CloudAccountId(message["cloud_account_id"]))
            case "cloud_account_deleted":
                pass  # we don't care about deleted accounts since the scheduling is done via the tenant id
            case _:
                log.error(f"Don't know how to handle messages of kind {context.kind}")

    async def process_collect_done_message(self, message: Json, context: MessageContext) -> None:
        match context.kind:
            case "collect-done":
                await self.collect_job_finished(message)
            case _:
                log.info(f"Collect messages: will ignore messages of kine {context.kind}")

    def _collect_progress_hash_key(self, workspace_id: WorkspaceId) -> str:
        return f"dispatching:collect_jobs_in_progress:{workspace_id}"

    async def complete_collect_job(self, tenant_id: WorkspaceId, completed_job_id: str) -> None:
        redis_set_key = self._collect_progress_hash_key(tenant_id)

        async def get_redis_hash() -> Dict[bytes, bytes]:
            result = await self.temp_store_redis.hgetall(redis_set_key)  # type: ignore
            return cast(Dict[bytes, bytes], result)

        def parse_collect_state(hash: Dict[bytes, bytes]) -> Dict[str, AccountCollectInProgress]:
            return {k.decode(): AccountCollectInProgress.from_json_bytes(v) for k, v in hash.items()}

        async def mark_job_as_done(progress: AccountCollectInProgress) -> AccountCollectInProgress:
            progress = progress.done()
            await self.temp_store_redis.hset(redis_set_key, completed_job_id, progress.to_json_str())  # type: ignore
            return progress

        def all_jobs_finished(collect_state: Dict[str, AccountCollectInProgress]) -> bool:
            return all(job.status == "done" for job in collect_state.values())

        async def send_domain_event(collect_state: Dict[str, AccountCollectInProgress]) -> None:
            collected_accounts = [CloudAccountId(job.account_id) for job in collect_state.values()]
            await self.domaim_event_sender.publish(TenantAccountsCollected(tenant_id, collected_accounts))

        # fetch the redis hash
        hash = await get_redis_hash()
        if not hash:
            log.error(f"Could not find any job context for tenant id {tenant_id}")
            return
        # parse it to dataclass
        tenant_collect_state = parse_collect_state(hash)
        if not (progress := tenant_collect_state.get(completed_job_id)):
            log.error(f"Could not find job context for job id {completed_job_id}")
            return
        # mark the job as done
        progress = await mark_job_as_done(progress)
        tenant_collect_state[completed_job_id] = progress
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
        account_info = message["account_info"]
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
        await self.metering_repo.add(records)
        await self.complete_collect_job(
            workspace_id,
            job_id,
        )

    async def cloud_account_created(self, cid: CloudAccountId) -> None:
        if account := await self.cloud_account_repo.get(cid):
            await self.trigger_collect(account)
            # store an entry in the next_run table
            next_run_at = await self.compute_next_run(account.workspace_id)
            await self.next_run_repo.create(account.workspace_id, next_run_at)
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

    async def _add_collect_in_progress_account(
        self, workspace_id: WorkspaceId, job_id: str, account_id: CloudAccountId
    ) -> None:
        value = AccountCollectInProgress(job_id, account_id, utc()).to_json_str()
        await self.temp_store_redis.hset(name=self._collect_progress_hash_key(workspace_id), key=job_id, value=value)  # type: ignore # noqa
        # cleanup after 4 hours just to be sure
        await self.temp_store_redis.expire(name=self._collect_progress_hash_key(workspace_id), time=timedelta(hours=4))

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

        if (ai := account_information()) and (
            db := await self.access_manager.get_database_access(account.workspace_id)
        ):
            job_id = str(uuid.uuid4())
            log.info(
                f"Trigger collect for tenant: {account.workspace_id} and account: {account.id} with job_id: {job_id}"
            )
            await self._add_collect_in_progress_account(account.workspace_id, job_id, account.id)
            await self.collect_queue.enqueue(db, ai, job_id=job_id)

    async def schedule_next_runs(self) -> None:
        now = utc()

        async def job_still_running(workspace_id: WorkspaceId) -> bool:
            hash_length: int = await self.temp_store_redis.hlen(self._collect_progress_hash_key(workspace_id))  # type: ignore # noqa
            return hash_length > 0

        async for workspace_id, at in self.next_run_repo.older_than(now):
            if await job_still_running(workspace_id):
                log.error(f"Job for tenant: {workspace_id} is still running. Will not schedule next run.")
                continue

            if accounts := await self.cloud_account_repo.list_by_workspace_id(workspace_id):
                for account in accounts:
                    await self.trigger_collect(account)
                next_run_at = await self.compute_next_run(workspace_id, at)
                await self.next_run_repo.update_next_run_at(workspace_id, next_run_at)
            else:
                log.error("Received a message, that a cloud account is created, but it does not exist in the database")
                continue
