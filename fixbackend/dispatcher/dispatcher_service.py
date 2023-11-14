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
from uuid import UUID

from fixcloudutils.asyncio.periodic import Periodic
from fixcloudutils.redis.event_stream import Json, MessageContext, RedisStreamListener
from fixcloudutils.service import Service
from fixcloudutils.util import parse_utc_str, utc
from redis.asyncio import Redis

from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount, CloudAccountStates
from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.collect.collect_queue import AccountInformation, AwsAccountInformation, CollectQueue
from fixbackend.dispatcher.collect_progress import AccountCollectProgress, CollectionSuccess
from fixbackend.dispatcher.next_run_repository import NextRunRepository
from fixbackend.domain_events.events import (
    AwsAccountConfigured,
    CloudAccountCollectInfo,
    TenantAccountsCollected,
    WorkspaceCreated,
)
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import CloudAccountId, FixCloudAccountId, WorkspaceId, AwsARN
from fixbackend.logging_context import set_workspace_id, set_fix_cloud_account_id, set_cloud_account_id
from fixbackend.metering import MeteringRecord
from fixbackend.metering.metering_repository import MeteringRepository

log = logging.getLogger(__name__)


CollectState = Dict[FixCloudAccountId, AccountCollectProgress]


class CollectAccountProgress:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    def _collect_progress_hash_key(self, workspace_id: WorkspaceId) -> str:
        return f"dispatching:collect_jobs_in_progress:{workspace_id}"

    def _jobs_hash_key(self, workspace_id: WorkspaceId) -> str:
        return f"dispatching:collect_jobs_in_progress:{workspace_id}:jobs"

    def _jobs_to_workspace_key(self, job_id: str) -> str:
        return f"dispatching:collect_jobs_in_progress:jobs_to_tenant:{job_id}"

    async def track_account_collection_progress(
        self,
        workspace_id: WorkspaceId,
        cloud_account_id: FixCloudAccountId,
        account_information: AccountInformation,
        job_id: UUID,
        now: datetime,
    ) -> None:
        if isinstance(account_information, AwsAccountInformation):
            account_id = account_information.aws_account_id
        else:
            raise NotImplementedError("Unsupported account information type")
        value = AccountCollectProgress(
            cloud_account_id=cloud_account_id, account_id=account_id, started_at=now
        ).to_json_str()
        # store account_collect_progress
        await self.redis.hset(
            name=self._collect_progress_hash_key(workspace_id), key=str(cloud_account_id), value=value
        )  # type: ignore
        # store job_id -> cloud_account_id mapping
        await self.redis.hset(name=self._jobs_hash_key(workspace_id), key=str(job_id), value=str(cloud_account_id))  # type: ignore

        # store job_id -> workspace_id mapping
        await self.redis.set(name=self._jobs_to_workspace_key(str(job_id)), value=str(workspace_id))
        # cleanup after 4 hours just to be sure
        expiration = timedelta(hours=4)

        await self.redis.expire(name=self._collect_progress_hash_key(workspace_id), time=expiration)
        await self.redis.expire(name=self._jobs_hash_key(workspace_id), time=expiration)
        await self.redis.expire(name=self._jobs_to_workspace_key(str(job_id)), time=expiration)

    async def get_tenant_collect_state(
        self, workspace_id: WorkspaceId
    ) -> Dict[FixCloudAccountId, AccountCollectProgress]:
        key = self._collect_progress_hash_key(workspace_id)
        hash = cast(Dict[str, str], (await self.redis.hgetall(key)))  # type: ignore
        return {FixCloudAccountId(UUID(k)): AccountCollectProgress.from_json_str(v) for k, v in hash.items()}

    async def get_account_collect_state(
        self, workspace_id: WorkspaceId, account_id: FixCloudAccountId
    ) -> Optional[AccountCollectProgress]:
        hash_key = self._collect_progress_hash_key(workspace_id)
        account_progress_str: Optional[str] = await self.redis.hget(hash_key, str(account_id))  # type: ignore
        if account_progress_str is None:
            return None
        return AccountCollectProgress.from_json_str(account_progress_str)

    async def get_account_collect_state_by_job_id(
        self, workspace_id: WorkspaceId, job_id: str
    ) -> Optional[AccountCollectProgress]:
        hash_key = self._jobs_hash_key(workspace_id)
        fix_cloud_account_id_str: Optional[str] = await self.redis.hget(hash_key, job_id)  # type: ignore
        if fix_cloud_account_id_str is None:
            log.warning(f"Could not find cloud account id for job id {job_id}")
            return None
        fix_cloud_account_id = FixCloudAccountId(UUID(fix_cloud_account_id_str))
        set_fix_cloud_account_id(fix_cloud_account_id)
        account = await self.get_account_collect_state(workspace_id, fix_cloud_account_id)
        if account is None:
            log.warning(f"Could not find account for cloud account id {fix_cloud_account_id}")
        return account

    async def account_collection_ongoing(self, workspace_id: WorkspaceId, cloud_account_id: FixCloudAccountId) -> bool:
        collect_state = await self.get_account_collect_state(workspace_id, cloud_account_id)
        if collect_state is None:
            return False
        return True

    async def mark_account_as_collected(
        self,
        workspace_id: WorkspaceId,
        cloud_account_id: FixCloudAccountId,
        nr_of_resources_collected: int,
        scan_duration_seconds: int,
    ) -> CollectState:
        hash_key = self._collect_progress_hash_key(workspace_id)

        collect_state = await self.get_tenant_collect_state(workspace_id)

        if cloud_account_id not in collect_state:
            raise Exception(f"Could not find collect job context for accound id {cloud_account_id}")
        collect_progress_done = collect_state[cloud_account_id].done(
            scanned_resources=nr_of_resources_collected, scan_duration=scan_duration_seconds
        )
        await self.redis.hset(
            hash_key, key=str(cloud_account_id), value=collect_progress_done.to_json_str()
        )  # type: ignore
        return collect_state | {cloud_account_id: collect_progress_done}

    async def workspace_id_from_job_id(self, job_id: str) -> Optional[WorkspaceId]:
        workspace_id_str: Optional[str] = await self.redis.get(self._jobs_to_workspace_key(UUID(job_id)))  # type: ignore # noqa
        if workspace_id_str is None:
            logging.warn(f"Could not find workspace id for job id {job_id}")
            return None

        return WorkspaceId(UUID(workspace_id_str))

    async def mark_job_as_failed(
        self,
        job_id: str,
        error: str,
    ) -> None:
        workspace_id = await self.workspace_id_from_job_id(job_id)
        if workspace_id is None:
            return
        set_workspace_id(workspace_id)
        hash_key = self._collect_progress_hash_key(workspace_id)

        cloud_account_state = await self.get_account_collect_state_by_job_id(workspace_id, job_id)
        if cloud_account_state is None:
            logging.warning(f"Could not find cloud account state for job id {job_id}")
            return

        failed = cloud_account_state.failed(error)
        await self.redis.hset(hash_key, key=str(failed.cloud_account_id), value=failed.to_json_str())  # type: ignore

    async def delete_tenant_collect_state(self, workspace_id: WorkspaceId) -> None:
        await self.redis.delete(self._collect_progress_hash_key(workspace_id))
        all_job_ids = await self.redis.hgetall(self._jobs_hash_key(workspace_id))  # type: ignore
        for job_id in all_job_ids.keys():
            await self.redis.delete(self._jobs_to_workspace_key(job_id))
        await self.redis.delete(self._jobs_hash_key(workspace_id))


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
        self.domain_event_sender = domain_event_sender
        self.collect_progress = CollectAccountProgress(temp_store_redis)

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
                set_workspace_id(str(wc_event.workspace_id))
                await self.workspace_created(wc_event.workspace_id)

            case AwsAccountConfigured.kind:
                awd_event = AwsAccountConfigured.from_json(message)
                set_fix_cloud_account_id(str(awd_event.cloud_account_id))
                set_workspace_id(str(awd_event.tenant_id))
                set_cloud_account_id(str(awd_event.aws_account_id))
                await self.cloud_account_configured(awd_event.cloud_account_id)

            case _:
                pass  # ignore other domain events

    async def process_collect_done_message(self, message: Json, context: MessageContext) -> None:
        match context.kind:
            case "collect-done":
                await self.collect_job_finished(message)
            case _:
                log.info(f"Collect messages: will ignore messages of kine {context.kind}")

    async def complete_collect_job(
        self,
        workspace_id: WorkspaceId,
    ) -> None:
        async def send_domain_event(collect_state: Dict[FixCloudAccountId, AccountCollectProgress]) -> None:
            collected_accounts = {
                k: CloudAccountCollectInfo(
                    v.account_id,
                    v.collection_done.scanned_resources,
                    v.collection_done.duration_seconds,
                    v.started_at,
                )
                for k, v in collect_state.items()
                if isinstance(v.collection_done, CollectionSuccess)
            }
            next_run = await self.next_run_repo.get(workspace_id)
            event = TenantAccountsCollected(workspace_id, collected_accounts, next_run)
            await self.domain_event_sender.publish(event)

        # check if we can send the domain event
        tenant_collect_state = await self.collect_progress.get_tenant_collect_state(workspace_id)

        if not all(job.is_done() for job in tenant_collect_state.values()):
            log.info("One of multiple jobs finished. Waiting for the remaining jobs.")
            return

        # all jobs are finished, send domain event and delete the hash
        await send_domain_event(tenant_collect_state)
        await self.collect_progress.delete_tenant_collect_state(workspace_id)

    async def collect_job_finished(self, message: Json) -> None:
        job_id = message["job_id"]

        async def handle_error(error: str) -> None:
            await self.collect_progress.mark_job_as_failed(job_id, error)
            log.warning(f"Collect job finished with an error: job_id={job_id}.")

        async def handle_success() -> None:
            task_id = message["task_id"]
            workspace_id = WorkspaceId(uuid.UUID(message["tenant_id"]))
            account_info: Dict[str, Any] = message["account_info"]
            messages = message["messages"]
            started_at = parse_utc_str(message["started_at"])
            duration = message["duration"]
            set_workspace_id(workspace_id)
            log.info(
                f"Collect job finished: job_id={job_id}, task_id={task_id}, workspace_id={workspace_id}. "
                f"Took {duration}. Messages: {messages}"
            )
            records = [
                MeteringRecord(
                    id=uuid.uuid4(),
                    workspace_id=workspace_id,
                    cloud=account_details["cloud"],
                    account_id=CloudAccountId(account_id),
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
            account_progress = await self.collect_progress.get_account_collect_state_by_job_id(workspace_id, job_id)
            if account_progress is None:
                log.error(f"Could not find collect job context for job_id {job_id}")
                return
            set_fix_cloud_account_id(account_progress.cloud_account_id)
            await self.collect_progress.mark_account_as_collected(
                workspace_id,
                account_progress.cloud_account_id,
                sum(r.nr_of_resources_collected for r in records),
                duration,
            )

        error: Optional[str] = message.get("error")
        if error:
            await handle_error(error)
        else:
            await handle_success()

        workspace_id = await self.collect_progress.workspace_id_from_job_id(job_id)
        if workspace_id is None:
            log.warning(f"Could not find workspace id for job id {job_id}")
            return
        await self.complete_collect_job(workspace_id)
        log.info("Successfully processed collect job finished message")

    async def workspace_created(self, workspace_id: WorkspaceId) -> None:
        # store an entry in the next_run table
        next_run_at = await self.compute_next_run(workspace_id)
        await self.next_run_repo.create(workspace_id, next_run_at)

    async def cloud_account_configured(self, cloud_account_id: FixCloudAccountId) -> None:
        if account := await self.cloud_account_repo.get(cloud_account_id):
            await self.trigger_collect(account)
        else:
            log.error(
                f"Received cloud account {cloud_account_id} configured message, but it does not exist in the database"
            )

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

    async def trigger_collect(self, account: CloudAccount) -> None:
        set_cloud_account_id(account.account_id)
        set_fix_cloud_account_id(account.id)
        if await self.collect_progress.account_collection_ongoing(account.workspace_id, account.id):
            log.info(f"Collect for tenant: {account.workspace_id} and account: {account.id} is already in progress.")
            return

        def account_information() -> Optional[AccountInformation]:
            match account.state:
                case CloudAccountStates.Configured(access, _) | CloudAccountStates.Degraded(access, _):
                    match access:
                        case AwsCloudAccess(external_id, role_name):
                            return AwsAccountInformation(
                                aws_account_id=account.account_id,
                                aws_account_name=account.account_name,
                                aws_role_arn=AwsARN(f"arn:aws:iam::{account.account_id}:role/{role_name}"),
                                external_id=external_id,
                            )
                        case _:
                            log.error(f"Don't know how to handle this cloud access {access}. Ignore it.")
                            return None
                case _:
                    log.error(f"Account {account.id} is not in configured state. Ignore it.")
                    return None

        if (ai := account_information()) and (
            db := await self.access_manager.get_database_access(account.workspace_id)
        ):
            job_id = uuid.uuid4()
            log.info(
                f"Trigger collect for tenant: {account.workspace_id} and account: {account.id} with job_id: {job_id}"
            )
            await self.collect_progress.track_account_collection_progress(
                account.workspace_id, account.id, ai, job_id, utc()
            )
            await self.collect_queue.enqueue(db, ai, job_id=str(job_id))

    async def schedule_next_runs(self) -> None:
        now = utc()

        async for workspace_id, at in self.next_run_repo.older_than(now):
            set_workspace_id(workspace_id)
            accounts = await self.cloud_account_repo.list_by_workspace_id(workspace_id, ready_for_collection=True)
            log.info(f"scheduling next run for workspace {workspace_id}, {len(accounts)} accounts")
            for account in accounts:
                await self.trigger_collect(account)
            next_run_at = await self.compute_next_run(workspace_id, at)
            log.info(f"next run for workspace {workspace_id} will be at {next_run_at}")
            await self.next_run_repo.update_next_run_at(workspace_id, next_run_at)
