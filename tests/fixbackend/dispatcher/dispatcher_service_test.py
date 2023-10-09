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
from datetime import timedelta, datetime, timezone
from typing import Optional

import pytest
from pytest import approx
from fixcloudutils.redis.event_stream import MessageContext
from fixcloudutils.util import utc
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.cloud_accounts.models import CloudAccount, AwsCloudAccess
from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.dispatcher.dispatcher_service import DispatcherService
from fixbackend.dispatcher.next_run_repository import NextRunRepository, NextRun
from fixbackend.ids import CloudAccountId, WorkspaceId
from fixbackend.metering.metering_repository import MeteringRepository
from fixbackend.workspaces.models import Workspace


@pytest.mark.asyncio
async def test_receive_cloud_account_created(
    dispatcher: DispatcherService,
    session: AsyncSession,
    cloud_account_repository: CloudAccountRepository,
    organization: Workspace,
    arq_redis: Redis,
) -> None:
    # create a cloud account
    cloud_account_id = CloudAccountId(uuid.uuid1())
    await cloud_account_repository.create(
        CloudAccount(cloud_account_id, organization.id, AwsCloudAccess("123", organization.external_id, "test"))
    )
    # signal to the dispatcher that the cloud account was created
    await dispatcher.process_cloud_account_changed_message(
        {"id": str(cloud_account_id)}, MessageContext("test", "cloud_account_created", "test", utc(), utc())
    )
    # check that a new entry was created in the next_run table
    next_run = await session.get(NextRun, cloud_account_id)
    assert next_run is not None
    assert next_run.at > utc()  # next run is in the future
    # check that two new entries are created in the work queue: (e.g.: arq:queue, arq:job:xxx)
    assert len(await arq_redis.keys()) == 2


@pytest.mark.asyncio
async def test_receive_cloud_account_deleted(
    dispatcher: DispatcherService, session: AsyncSession, next_run_repository: NextRunRepository
) -> None:
    # create cloud
    cloud_account_id = CloudAccountId(uuid.uuid1())
    # create a next run entry
    await next_run_repository.create(cloud_account_id, utc())
    # signal to the dispatcher that the cloud account was created
    await dispatcher.process_cloud_account_changed_message(
        {"id": str(cloud_account_id)}, MessageContext("test", "cloud_account_deleted", "test", utc(), utc())
    )
    # check that a new entry was created in the next_run table
    next_run = await session.get(NextRun, cloud_account_id)
    assert next_run is None


@pytest.mark.asyncio
async def test_trigger_collect(
    dispatcher: DispatcherService,
    session: AsyncSession,
    cloud_account_repository: CloudAccountRepository,
    next_run_repository: NextRunRepository,
    organization: Workspace,
    arq_redis: Redis,
) -> None:
    # create a cloud account and next_run entry
    cloud_account_id = CloudAccountId(uuid.uuid1())
    account = CloudAccount(cloud_account_id, organization.id, AwsCloudAccess("123", organization.external_id, "test"))
    await cloud_account_repository.create(account)
    # Create a next run entry scheduled in the past - it should be picked up for collect
    await next_run_repository.create(cloud_account_id, utc() - timedelta(hours=1))

    # schedule runs: make sure a collect is triggered and the next_run is updated
    await dispatcher.schedule_next_runs()
    next_run = await session.get(NextRun, cloud_account_id)
    assert next_run is not None
    assert next_run.at > utc()  # next run is in the future
    # check that two new entries are created in the work queue: (e.g.: arq:queue, arq:job:xxx)
    assert len(await arq_redis.keys()) == 2

    # another run should not change anything
    await dispatcher.schedule_next_runs()
    again = await session.get(NextRun, cloud_account_id)
    assert again is not None
    assert again.at == next_run.at
    assert len(await arq_redis.keys()) == 2


@pytest.mark.asyncio
async def test_receive_collect_done_message(
    dispatcher: DispatcherService, metering_repository: MeteringRepository, organization: Workspace
) -> None:
    message = {
        "job_id": "j1",
        "task_id": "t1",
        "tenant_id": str(organization.id),
        "account_info": {
            "account1": dict(
                id="account1",
                name="test",
                cloud="aws",
                exported_at="2023-09-29T09:00:18Z",
                summary={"instance": 23, "volume": 12},
            ),
            "account2": dict(
                id="account2",
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
    await dispatcher.process_collect_done_message(message, context)
    result = [n async for n in metering_repository.list(organization.id)]
    assert len(result) == 2
    mr_1, mr_2 = result if result[0].account_name == "test" else list(reversed(result))
    assert mr_1.workspace_id == organization.id
    assert mr_1.job_id == "j1"
    assert mr_1.task_id == "t1"
    assert mr_1.cloud == "aws"
    assert mr_1.account_id == "account1"
    assert mr_1.account_name == "test"
    assert mr_1.nr_of_resources_collected == 35
    assert mr_1.nr_of_error_messages == 2
    assert mr_1.started_at == datetime(2023, 9, 29, 9, 0, tzinfo=timezone.utc)
    assert mr_1.duration == 18
    assert mr_2.workspace_id == organization.id
    assert mr_2.job_id == "j1"
    assert mr_2.task_id == "t1"
    assert mr_2.cloud == "k8s"
    assert mr_2.account_id == "account2"
    assert mr_2.account_name == "foo"
    assert mr_2.nr_of_resources_collected == 25
    assert mr_2.nr_of_error_messages == 2
    assert mr_2.started_at == datetime(2023, 9, 29, 9, 0, tzinfo=timezone.utc)
    assert mr_2.duration == 18


@pytest.mark.asyncio
async def test_compute_next_run(dispatcher: DispatcherService) -> None:
    tenant = WorkspaceId(uuid.uuid4())
    delta = timedelta(hours=1)

    async def assert_next_is(last_run: Optional[datetime], expected: datetime) -> None:
        assert (await dispatcher.compute_next_run(tenant, last_run)).timestamp() == approx(expected.timestamp(), abs=2)

    now = utc()
    await assert_next_is(None, now + delta)
    await assert_next_is(now, now + delta)
    await assert_next_is(now + timedelta(seconds=10), now + delta + timedelta(seconds=10))
    await assert_next_is(now - timedelta(seconds=10), now + delta - timedelta(seconds=10))
    await assert_next_is(now + 3 * delta, now + 4 * delta)
    await assert_next_is(now - 3 * delta, now + delta)
    await assert_next_is(now - 123 * delta, now + delta)
