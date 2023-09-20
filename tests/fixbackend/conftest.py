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
from asyncio import AbstractEventLoop
from typing import Iterator, AsyncIterator

import pytest
from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

from fixbackend.collect.collect_queue import RedisCollectQueue
from fixbackend.config import Config
from fixbackend.db_handler.graph_db_access import GraphDatabaseAccessHolder, GraphDatabaseAccessManager


@pytest.fixture(scope="session")
def event_loop() -> Iterator[AbstractEventLoop]:
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def default_config() -> Config:
    return Config(
        instance_id="",
        database_name="",
        database_user="",
        database_password=None,
        database_host="",
        database_port=3306,
        secret="",
        google_oauth_client_id="",
        google_oauth_client_secret="",
        github_oauth_client_id="",
        github_oauth_client_secret="",
        redis_readwrite_url="redis://localhost:6379/0",
        redis_readonly_url="redis://localhost:6379/0",
        redis_queue_url="redis://localhost:6379/5",
        cdn_enpoint="",
        cdn_bucket="",
        fixui_sha="",
        static_assets=None,
        session_ttl=3600,
        oauth_redirect_url="/",
    )


@pytest.fixture
def graph_database_access_holder() -> GraphDatabaseAccessHolder:
    return GraphDatabaseAccessHolder()


@pytest.fixture
def graph_database_access_manager() -> GraphDatabaseAccessManager:
    return GraphDatabaseAccessManager()


@pytest.fixture
async def arq_redis() -> AsyncIterator[ArqRedis]:
    redis = await create_pool(RedisSettings(host="localhost", port=6379, database=5))
    # make sure we have a clean database
    keys = await redis.keys()
    if keys:
        await redis.delete(*keys)
    yield redis
    await redis.close()


@pytest.fixture
async def collect_queue(arq_redis: ArqRedis) -> RedisCollectQueue:
    return RedisCollectQueue(arq_redis)
