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
from datetime import datetime, timedelta

import pytest
from fixcloudutils.redis.event_stream import MessageContext
from fixcloudutils.util import utc
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.cloud_accounts.models import CloudAccount, AwsCloudAccess
from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.dispatcher.dispatcher_service import DispatcherService
from fixbackend.dispatcher.next_run_repository import NextRunRepository, NextRun
from fixbackend.ids import CloudAccountId
from fixbackend.organizations.models import Organization


@pytest.mark.asyncio
async def test_receive_created(
    dispatcher: DispatcherService,
    session: AsyncSession,
    cloud_account_repository: CloudAccountRepository,
    organization: Organization,
    arq_redis: Redis,
) -> None:
    # create a cloud account
    cloud_account_id = CloudAccountId(uuid.uuid1())
    await cloud_account_repository.create(
        CloudAccount(cloud_account_id, organization.id, AwsCloudAccess("123", organization.external_id, "test"))
    )
    # signal to the dispatcher that the cloud account was created
    await dispatcher.process_message(
        {"id": str(cloud_account_id)}, MessageContext("test", "cloud_account_created", "test", utc(), utc())
    )
    # check that a new entry was created in the next_run table
    next_run = await session.get(NextRun, cloud_account_id)
    assert next_run is not None
    assert next_run.at > datetime.now()  # next run is in the future
    # check that two new entries are created in the work queue: (e.g.: arq:queue, arq:job:xxx)
    assert len(await arq_redis.keys()) == 2


@pytest.mark.asyncio
async def test_receive_deleted(
    dispatcher: DispatcherService, session: AsyncSession, next_run_repository: NextRunRepository
) -> None:
    # create cloud
    cloud_account_id = CloudAccountId(uuid.uuid1())
    # create a next run entry
    await next_run_repository.create(cloud_account_id, utc())
    # signal to the dispatcher that the cloud account was created
    await dispatcher.process_message(
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
    organization: Organization,
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
    assert next_run.at > datetime.now()  # next run is in the future
    # check that two new entries are created in the work queue: (e.g.: arq:queue, arq:job:xxx)
    assert len(await arq_redis.keys()) == 2

    # another run should not change anything
    await dispatcher.schedule_next_runs()
    again = await session.get(NextRun, cloud_account_id)
    assert again.at == next_run.at
    assert len(await arq_redis.keys()) == 2
