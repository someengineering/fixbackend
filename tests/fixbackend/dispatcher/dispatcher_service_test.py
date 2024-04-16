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
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import pytest
from fixcloudutils.redis.event_stream import MessageContext
from fixcloudutils.util import utc
from pytest import approx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.auth.models import User
from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount, CloudAccountStates
from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.collect.collect_queue import AwsAccountInformation
from fixbackend.dispatcher.collect_progress import AccountCollectProgress
from fixbackend.dispatcher.dispatcher_service import DispatcherService
from fixbackend.dispatcher.next_run_repository import NextTenantRun
from fixbackend.domain_events.events import (
    AwsAccountConfigured,
    CloudAccountCollectInfo,
    TenantAccountsCollected,
    WorkspaceCreated,
)
from fixbackend.ids import (
    AwsARN,
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
)
from fixbackend.metering.metering_repository import MeteringRepository
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.config import ProductTierSettings
from tests.fixbackend.conftest import InMemoryDomainEventPublisher


@pytest.mark.asyncio
async def test_receive_workspace_created(
    dispatcher: DispatcherService,
    session: AsyncSession,
    cloud_account_repository: CloudAccountRepository,
    workspace: Workspace,
    user: User,
) -> None:
    # create a cloud account
    cloud_account_id = FixCloudAccountId(uuid.uuid1())
    aws_account_id = CloudAccountId("123")
    await cloud_account_repository.create(
        CloudAccount(
            id=cloud_account_id,
            workspace_id=workspace.id,
            account_name=CloudAccountName("foo"),
            account_id=aws_account_id,
            cloud=CloudNames.AWS,
            state=CloudAccountStates.Configured(
                AwsCloudAccess(
                    workspace.external_id,
                    AwsRoleName("test"),
                ),
                enabled=True,
                scan=True,
            ),
            account_alias=CloudAccountAlias("foo_alias"),
            user_account_name=UserCloudAccountName("foo_user"),
            privileged=False,
            last_scan_duration_seconds=0,
            last_scan_resources_scanned=0,
            last_scan_started_at=None,
            next_scan=None,
            created_at=utc(),
            updated_at=utc(),
            state_updated_at=utc(),
            cf_stack_version=0,
            failed_scan_count=0,
        )
    )
    # signal to the dispatcher that the new workspace was created
    await dispatcher.process_workspace_created(
        WorkspaceCreated(workspace.id, workspace.name, workspace.slug, user.id),
    )
    # check that a new entry was created in the next_run table
    next_run = await session.get(NextTenantRun, workspace.id)
    assert next_run is not None
    assert next_run.at > utc()  # next run is in the future


@pytest.mark.asyncio
async def test_receive_aws_account_configured(
    dispatcher: DispatcherService,
    session: AsyncSession,
    cloud_account_repository: CloudAccountRepository,
    workspace: Workspace,
    arq_redis: Redis,
    redis: Redis,
) -> None:
    # create a cloud account and next_run entry
    cloud_account_id = FixCloudAccountId(uuid.uuid1())
    aws_account_id = CloudAccountId("123")

    account = CloudAccount(
        id=cloud_account_id,
        workspace_id=workspace.id,
        account_id=aws_account_id,
        cloud=CloudNames.AWS,
        account_name=CloudAccountName("foo"),
        state=CloudAccountStates.Configured(
            AwsCloudAccess(workspace.external_id, AwsRoleName("test")), enabled=True, scan=True
        ),
        account_alias=CloudAccountAlias("foo_alias"),
        user_account_name=UserCloudAccountName("foo_user"),
        privileged=False,
        last_scan_duration_seconds=10,
        last_scan_resources_scanned=100,
        last_scan_started_at=utc(),
        next_scan=utc(),
        created_at=utc(),
        updated_at=utc(),
        state_updated_at=utc(),
        cf_stack_version=0,
        failed_scan_count=0,
    )
    await cloud_account_repository.create(account)

    # signal to the dispatcher that the cloud account was discovered
    await dispatcher.process_aws_account_configured(
        AwsAccountConfigured(cloud_account_id, workspace.id, aws_account_id),
    )

    # check that no new entry was created in the next_run table
    next_run = await session.get(NextTenantRun, workspace.id)
    assert next_run is None

    # check two job queues were created
    assert len(await arq_redis.keys()) == 2
    # check that 2 new entries are created in the redis: one progress hash, one jobs mapping, one job -> workspace key
    assert len(await redis.keys()) == 3
    in_progress_hash: Dict[bytes, bytes] = await redis.hgetall(
        dispatcher.collect_progress._collect_progress_hash_key(workspace.id)
    )  # type: ignore # noqa
    assert len(in_progress_hash) == 1
    progress = AccountCollectProgress.from_json_str(list(in_progress_hash.values())[0])
    assert progress.cloud_account_id == cloud_account_id
    assert progress.account_id == aws_account_id
    assert progress.is_done() is False

    # concurrent event does not create a new entry in the work queue
    # signal to the dispatcher that the cloud account was discovered
    await dispatcher.process_aws_account_configured(
        AwsAccountConfigured(cloud_account_id, workspace.id, aws_account_id),
    )
    assert len(await arq_redis.keys()) == 2
    assert len(await redis.keys()) == 3
    new_in_progress_hash: Dict[bytes, bytes] = await redis.hgetall(
        dispatcher.collect_progress._collect_progress_hash_key(workspace.id)
    )  # type: ignore # noqa
    assert len(new_in_progress_hash) == 1
    assert AccountCollectProgress.from_json_str(list(new_in_progress_hash.values())[0]) == progress


@pytest.mark.asyncio
async def test_receive_collect_done_message(
    dispatcher: DispatcherService,
    metering_repository: MeteringRepository,
    workspace: Workspace,
    domain_event_sender: InMemoryDomainEventPublisher,
    arq_redis: Redis,
    redis: Redis,
) -> None:
    async def in_progress_hash_len() -> int:
        in_progress_hash: Dict[bytes, bytes] = await redis.hgetall(
            dispatcher.collect_progress._collect_progress_hash_key(workspace.id)
        )  # type: ignore # noqa
        return len(in_progress_hash)

    async def jobs_mapping_hash_len() -> int:
        in_progress_hash: Dict[bytes, bytes] = await redis.hgetall(
            dispatcher.collect_progress._jobs_hash_key(workspace.id)
        )  # type: ignore # noqa
        return len(in_progress_hash)

    current_events_length = len(domain_event_sender.events)
    job_id = uuid.uuid4()
    cloud_account_id = FixCloudAccountId(uuid.uuid4())
    aws_account_id = CloudAccountId("123")
    k8s_account_id = CloudAccountId("456")
    message = {
        "job_id": str(job_id),
        "task_id": "t1",
        "tenant_id": str(workspace.id),
        "account_info": {
            aws_account_id: dict(
                id=aws_account_id,
                name="test",
                cloud="aws",
                exported_at="2023-09-29T09:00:18Z",
                summary={"instance": 23, "volume": 12},
            ),
            k8s_account_id: dict(
                id=k8s_account_id,
                name="foo",
                cloud="k8s",
                exported_at="2023-09-29T09:00:18Z",
                summary={"instance": 12, "volume": 13},
            ),
        },
        "messages": ["m1", "m2"],
        "started_at": "2023-09-29T09:00:00Z",
        "duration": 18,
    }
    context = MessageContext("test", "collect-done", "test", utc(), utc())
    now = utc()
    external_id = ExternalId(uuid.uuid4())
    await dispatcher.collect_progress.track_account_collection_progress(
        workspace.id,
        cloud_account_id,
        AwsAccountInformation(
            aws_account_id=aws_account_id,
            aws_account_name=CloudAccountName("test"),
            aws_role_arn=AwsARN("arn"),
            external_id=external_id,
        ),
        job_id,
        now,
    )
    assert await in_progress_hash_len() == 1
    assert await jobs_mapping_hash_len() == 1
    assert await redis.exists(dispatcher.collect_progress._jobs_to_workspace_key(str(job_id))) == 1
    assert await dispatcher.collect_progress.account_collection_ongoing(workspace.id, cloud_account_id) is True

    await dispatcher.process_collect_done_message(message, context)
    assert await in_progress_hash_len() == 0
    assert await jobs_mapping_hash_len() == 0
    assert await redis.exists(dispatcher.collect_progress._jobs_to_workspace_key(str(job_id))) == 0
    assert await dispatcher.collect_progress.account_collection_ongoing(workspace.id, cloud_account_id) is False

    result = [n async for n in metering_repository.list(workspace.id)]
    assert len(result) == 2
    mr_1, mr_2 = result if result[0].account_name == "test" else list(reversed(result))
    assert mr_1.workspace_id == workspace.id
    assert mr_1.job_id == str(job_id)
    assert mr_1.task_id == "t1"
    assert mr_1.cloud == "aws"
    assert mr_1.account_id == aws_account_id
    assert mr_1.account_name == "test"
    assert mr_1.nr_of_resources_collected == 35
    assert mr_1.nr_of_error_messages == 2
    assert mr_1.started_at == datetime(2023, 9, 29, 9, 0, tzinfo=timezone.utc)
    assert mr_1.duration == 18
    assert mr_2.workspace_id == workspace.id
    assert mr_2.job_id == str(job_id)
    assert mr_2.task_id == "t1"
    assert mr_2.cloud == "k8s"
    assert mr_2.account_id == k8s_account_id
    assert mr_2.account_name == "foo"
    assert mr_2.nr_of_resources_collected == 25
    assert mr_2.nr_of_error_messages == 2
    assert mr_2.started_at == datetime(2023, 9, 29, 9, 0, tzinfo=timezone.utc)
    assert mr_2.duration == 18

    assert len(domain_event_sender.events) == current_events_length + 1
    assert domain_event_sender.events[-1] == TenantAccountsCollected(
        workspace.id,
        {
            cloud_account_id: CloudAccountCollectInfo(
                mr_1.account_id,
                mr_1.nr_of_resources_collected + mr_2.nr_of_resources_collected,
                mr_1.duration,
                now,
                TaskId(mr_1.task_id),
            )
        },
        None,
    )


@pytest.mark.asyncio
async def test_receive_collect_done_message_zero_collected_accounts(
    dispatcher: DispatcherService,
    metering_repository: MeteringRepository,
    workspace: Workspace,
    domain_event_sender: InMemoryDomainEventPublisher,
    arq_redis: Redis,
    redis: Redis,
) -> None:
    async def in_progress_hash_len() -> int:
        in_progress_hash: Dict[bytes, bytes] = await redis.hgetall(
            dispatcher.collect_progress._collect_progress_hash_key(workspace.id)
        )  # type: ignore # noqa
        return len(in_progress_hash)

    async def jobs_mapping_hash_len() -> int:
        in_progress_hash: Dict[bytes, bytes] = await redis.hgetall(
            dispatcher.collect_progress._jobs_hash_key(workspace.id)
        )  # type: ignore # noqa
        return len(in_progress_hash)

    current_events_length = len(domain_event_sender.events)
    job_id = uuid.uuid4()
    cloud_account_id = FixCloudAccountId(uuid.uuid4())
    message = {
        "job_id": str(job_id),
        "task_id": "t1",
        "tenant_id": str(workspace.id),
        "account_info": {},
        "messages": ["m1", "m2"],
        "started_at": "2023-09-29T09:00:00Z",
        "duration": 18,
    }
    context = MessageContext("test", "collect-done", "test", utc(), utc())

    await dispatcher.process_collect_done_message(message, context)
    assert await in_progress_hash_len() == 0
    assert await jobs_mapping_hash_len() == 0
    assert await redis.exists(dispatcher.collect_progress._jobs_to_workspace_key(str(job_id))) == 0
    assert await dispatcher.collect_progress.account_collection_ongoing(workspace.id, cloud_account_id) is False

    # no event is emitted in case of no collected accounts
    for evt in domain_event_sender.events:
        print(evt)
    assert len(domain_event_sender.events) == current_events_length


@pytest.mark.asyncio
async def test_receive_collect_error_message(
    dispatcher: DispatcherService,
    metering_repository: MeteringRepository,
    workspace: Workspace,
    domain_event_sender: InMemoryDomainEventPublisher,
    arq_redis: Redis,
    redis: Redis,
) -> None:
    async def in_progress_hash_len() -> int:
        in_progress_hash: Dict[bytes, bytes] = await redis.hgetall(
            dispatcher.collect_progress._collect_progress_hash_key(workspace.id)
        )  # type: ignore # noqa
        return len(in_progress_hash)

    async def jobs_mapping_hash_len() -> int:
        in_progress_hash: Dict[bytes, bytes] = await redis.hgetall(
            dispatcher.collect_progress._jobs_hash_key(workspace.id)
        )  # type: ignore # noqa
        return len(in_progress_hash)

    current_events_length = len(domain_event_sender.events)
    job_id = uuid.uuid4()
    cloud_account_id = FixCloudAccountId(uuid.uuid4())
    aws_account_id = CloudAccountId("123")
    error = "some error"
    message = {
        "job_id": str(job_id),
        "error": error,
    }
    context = MessageContext("test", "collect-done", "test", utc(), utc())

    error_context = MessageContext("test", "job-failed", "test", utc(), utc())

    now = utc()
    external_id = ExternalId(uuid.uuid4())
    await dispatcher.collect_progress.track_account_collection_progress(
        workspace.id,
        cloud_account_id,
        AwsAccountInformation(
            aws_account_id=aws_account_id,
            aws_account_name=CloudAccountName("test"),
            aws_role_arn=AwsARN("arn"),
            external_id=external_id,
        ),
        job_id,
        now,
    )
    assert await in_progress_hash_len() == 1
    assert await jobs_mapping_hash_len() == 1
    assert await redis.get(dispatcher.collect_progress._jobs_to_workspace_key(str(job_id))) == str(workspace.id)
    assert await dispatcher.collect_progress.account_collection_ongoing(workspace.id, cloud_account_id) is True

    await dispatcher.process_collect_done_message(message, context)
    assert await in_progress_hash_len() == 0
    assert await jobs_mapping_hash_len() == 0
    assert await dispatcher.collect_progress.account_collection_ongoing(workspace.id, cloud_account_id) is False

    await dispatcher.process_collect_done_message(message, error_context)
    assert await in_progress_hash_len() == 0
    assert await jobs_mapping_hash_len() == 0
    assert await dispatcher.collect_progress.account_collection_ongoing(workspace.id, cloud_account_id) is False

    result = [n async for n in metering_repository.list(workspace.id)]
    assert len(result) == 0

    # no event is emitted in case of failure
    assert len(domain_event_sender.events) == current_events_length


@pytest.mark.asyncio
async def test_compute_next_run(
    dispatcher: DispatcherService,
    workspace: Workspace,
    workspace_repository: WorkspaceRepository,
    subscription: AwsMarketplaceSubscription,
) -> None:

    await workspace_repository.update_subscription(workspace.id, subscription.id)

    for product_tier in ProductTier:

        workspace = await workspace_repository.update_product_tier(workspace.id, product_tier)

        settings = ProductTierSettings[workspace.product_tier]

        delta = settings.scan_interval

        async def assert_next_is(last_run: Optional[datetime], expected: datetime) -> None:
            assert (await dispatcher.compute_next_run(workspace.id, last_run)).timestamp() == approx(
                expected.timestamp(), abs=2
            )

        now = utc()
        await assert_next_is(None, now + delta)
        await assert_next_is(now, now + delta)
        await assert_next_is(now + timedelta(seconds=10), now + delta + timedelta(seconds=10))
        await assert_next_is(now - timedelta(seconds=10), now + delta - timedelta(seconds=10))
        await assert_next_is(now + 3 * delta, now + 4 * delta)
        await assert_next_is(now - 3 * delta, now + delta)
        await assert_next_is(now - 123 * delta, now + delta)
