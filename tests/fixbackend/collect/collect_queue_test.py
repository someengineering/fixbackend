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
import pytest
from redis.asyncio import Redis

from fixbackend.collect.collect_queue import RedisCollectQueue, JobAlreadyEnqueued
from fixbackend.db_handler.graph_db_access import GraphDatabaseAccessHolder


@pytest.mark.asyncio
async def test_redis_collect_queue(
    arq_redis: Redis, collect_queue: RedisCollectQueue, graph_database_access_holder: GraphDatabaseAccessHolder
) -> None:
    # assert no keys in redis
    assert set(await arq_redis.keys()) == set()
    # enqueue new job
    access = graph_database_access_holder.database_for_current_tenant()
    config = {"resotoworker": {"collector": ["aws"]}}
    await collect_queue.enqueue(access, config, 1, job_id="test")
    assert set(await arq_redis.keys()) == {b"arq:queue", b"arq:job:test"}
    # enqueue again will fail
    with pytest.raises(JobAlreadyEnqueued):
        await collect_queue.enqueue(access, config, 1, job_id="test")
