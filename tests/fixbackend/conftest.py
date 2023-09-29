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
import json
from argparse import Namespace
from asyncio import AbstractEventLoop
from typing import AsyncIterator, Iterator, List

import pytest
from alembic.command import upgrade as alembic_upgrade
from alembic.config import Config as AlembicConfig
from arq import ArqRedis, create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fixcloudutils.types import Json
from httpx import AsyncClient, MockTransport, Request, Response
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy_utils import create_database, database_exists, drop_database

from fixbackend.app import fast_api_app
from fixbackend.cloud_accounts.repository import CloudAccountRepository, CloudAccountRepositoryImpl
from fixbackend.auth.db import get_user_repository
from fixbackend.auth.models import User
from fixbackend.collect.collect_queue import RedisCollectQueue
from fixbackend.config import Config, get_config
from fixbackend.db import get_async_session
from fixbackend.dependencies import FixDependencies, ServiceNames, fix_dependencies
from fixbackend.dispatcher.dispatcher_service import DispatcherService
from fixbackend.dispatcher.next_run_repository import NextRunRepository
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.inventory.inventory_client import InventoryClient
from fixbackend.inventory.inventory_service import InventoryService
from fixbackend.metering.metering_repository import MeteringRepository
from fixbackend.organizations.models import Organization
from fixbackend.organizations.service import OrganizationService
from fixbackend.types import AsyncSessionMaker

DATABASE_URL = "mysql+aiomysql://root@127.0.0.1:3306/fixbackend-testdb"
# only used to create/drop the database
SYNC_DATABASE_URL = "mysql+pymysql://root@127.0.0.1:3306/fixbackend-testdb"


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
        database_name="fixbackend-testdb",
        database_user="root",
        database_password=None,
        database_host="127.0.0.1",
        database_port=3306,
        secret="",
        google_oauth_client_id="",
        google_oauth_client_secret="",
        github_oauth_client_id="",
        github_oauth_client_secret="",
        redis_readwrite_url="redis://localhost:6379/0",
        redis_readonly_url="redis://localhost:6379/0",
        redis_queue_url="redis://localhost:6379/5",
        cdn_endpoint="",
        cdn_bucket="",
        fixui_sha="",
        static_assets=None,
        session_ttl=3600,
        available_db_server=["http://localhost:8529", "http://127.0.0.1:8529"],
        inventory_url="http://localhost:8980",
        cf_template_url="dev-eu",
        args=Namespace(dispatcher=False),
    )


@pytest.fixture(scope="session")
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """
    Creates a new database for a test and runs the migrations.
    """
    # make sure the db exists and it is clean
    if database_exists(SYNC_DATABASE_URL):
        drop_database(SYNC_DATABASE_URL)
    create_database(SYNC_DATABASE_URL)

    while not database_exists(SYNC_DATABASE_URL):
        await asyncio.sleep(0.1)

    engine = create_async_engine(DATABASE_URL)
    alembic_config = AlembicConfig("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", DATABASE_URL)
    await asyncio.to_thread(alembic_upgrade, alembic_config, "head")  # noqa

    yield engine

    await engine.dispose()
    try:
        drop_database(SYNC_DATABASE_URL)
    except Exception:
        pass


@pytest.fixture
async def session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """
    Creates a new database session for a test, that is bound to the
    database transaction and rolled back after the test is done.

    Allows for running tests in parallel.
    """
    connection = db_engine.connect()
    await connection.start()
    transaction = connection.begin()
    await transaction.start()
    session = AsyncSession(bind=connection)

    yield session

    await session.close()
    await transaction.close()
    await connection.close()


@pytest.fixture
def async_session_maker(session: AsyncSession) -> AsyncSessionMaker:
    def get_session() -> AsyncSession:
        return session

    return get_session


@pytest.fixture
def graph_database_access_manager(
    default_config: Config, async_session_maker: AsyncSessionMaker
) -> GraphDatabaseAccessManager:
    return GraphDatabaseAccessManager(default_config, async_session_maker)


@pytest.fixture
def organisation_service(
    session: AsyncSession, graph_database_access_manager: GraphDatabaseAccessManager
) -> OrganizationService:
    return OrganizationService(session, graph_database_access_manager)


@pytest.fixture
async def user(session: AsyncSession) -> User:
    user_db = await anext(get_user_repository(session))
    user_dict = {
        "email": "foo@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    return await user_db.create(user_dict)


@pytest.fixture
async def organization(organization_repository: OrganizationService, user: User) -> Organization:
    return await organization_repository.create_organization("foo", "foo", user)


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


@pytest.fixture
async def benchmark_json() -> List[Json]:
    return [
        {"id": "a", "type": "node", "reported": {"kind": "report_benchmark", "name": "benchmark_name"}},
        {"id": "b", "type": "node", "reported": {"kind": "report_check_result", "title": "Something"}},
        {"from": "a", "to": "b", "type": "edge", "edge_type": "default"},
    ]


@pytest.fixture
async def inventory_client(benchmark_json: List[Json]) -> AsyncIterator[InventoryClient]:
    async def app(request: Request) -> Response:
        content = request.content.decode("utf-8")
        if request.url.path == "/cli/execute" and content == "json [1,2,3]":
            return Response(200, content=b'"1"\n"2"\n"3"\n', headers={"content-type": "application/x-ndjson"})
        elif request.url.path == "/cli/execute" and content == "report benchmark load benchmark_name | dump":
            response = ""
            for a in benchmark_json:
                response += json.dumps(a) + "\n"
            return Response(200, content=response.encode("utf-8"), headers={"content-type": "application/x-ndjson"})
        elif request.url.path == "/report/benchmarks":
            info = [
                {"clouds": ["aws"], "description": "Test AWS", "framework": "CIS", "id": "aws_test", "report_checks": ["aws_c1", "aws_c2"], "title": "AWS Test", "version": "0.1"},  # fmt: skip
                {"clouds": ["gcp"], "description": "Test GCP", "framework": "CIS", "id": "gcp_test", "report_checks": ["gcp_c1", "gcp_c2"], "title": "GCP Test", "version": "0.2"},  # fmt: skip
            ]
            return Response(200, content=json.dumps(info).encode("utf-8"), headers={"content-type": "application/json"})
        elif request.url.path == "/graph/resoto/search/list" and content == "is (account)":
            result_list = [
                {"id": "n1", "type": "node", "reported": {"id": "234", "name": "account 1"}, "ancestors": {"cloud": {"reported": {"name": "gcp", "id": "gcp"}}}},  # fmt: skip
                {"id": "n2", "type": "node", "reported": {"id": "123", "name": "account 2"}, "ancestors": {"cloud": {"reported": {"name": "aws", "id": "aws"}}}}  # fmt: skip
            ]
            response = ""
            for a in result_list:
                response += json.dumps(a) + "\n"
            return Response(200, content=response.encode("utf-8"), headers={"content-type": "application/x-ndjson"})
        elif request.url.path == "/graph/resoto/search/aggregate":
            aggregated = [
                {"group": {"check_id": "aws_c1", "severity": "low", "account_id": "123", "account_name": "t1", "cloud": "aws"}, "sum_of_1": 8},  # fmt: skip
                {"group": {"check_id": "gcp_c2", "severity": "critical", "account_id": "234", "account_name": "t2", "cloud": "gcp"}, "sum_of_1": 2}  # fmt: skip
            ]
            response = ""
            for a in aggregated:
                response += json.dumps(a) + "\n"
            return Response(200, content=response.encode("utf-8"), headers={"content-type": "application/x-ndjson"})
        else:
            raise Exception(f"Unexpected request: {request.url.path} with content {content}")

    async_client = AsyncClient(transport=MockTransport(app))
    async with InventoryClient("http://localhost:8980", client=async_client) as client:
        yield client


@pytest.fixture
async def inventory_service(inventory_client: InventoryClient) -> AsyncIterator[InventoryService]:
    async with InventoryService(inventory_client) as service:
        yield service


@pytest.fixture
async def next_run_repository(async_session_maker: AsyncSessionMaker) -> NextRunRepository:
    return NextRunRepository(async_session_maker)


@pytest.fixture
async def cloud_account_repository(async_session_maker: AsyncSessionMaker) -> CloudAccountRepository:
    return CloudAccountRepositoryImpl(async_session_maker)


@pytest.fixture
async def metering_repository(async_session_maker: AsyncSessionMaker) -> MeteringRepository:
    return MeteringRepository(async_session_maker)


@pytest.fixture
async def organization_repository(
    session: AsyncSession, graph_database_access_manager: GraphDatabaseAccessManager
) -> OrganizationService:
    return OrganizationService(session, graph_database_access_manager)


@pytest.fixture
async def dispatcher(
    arq_redis: ArqRedis,
    cloud_account_repository: CloudAccountRepository,
    next_run_repository: NextRunRepository,
    metering_repository: MeteringRepository,
    collect_queue: RedisCollectQueue,
    graph_database_access_manager: GraphDatabaseAccessManager,
) -> DispatcherService:
    return DispatcherService(
        arq_redis,
        cloud_account_repository,
        next_run_repository,
        metering_repository,
        collect_queue,
        graph_database_access_manager,
    )


@pytest.fixture
async def fix_deps(
    db_engine: AsyncEngine, graph_database_access_manager: GraphDatabaseAccessManager
) -> FixDependencies:
    return FixDependencies(
        **{ServiceNames.async_engine: db_engine, ServiceNames.graph_db_access: graph_database_access_manager}
    )


@pytest.fixture
async def fast_api(fix_deps: FixDependencies, session: AsyncSession, default_config: Config) -> FastAPI:
    app = fast_api_app(default_config)
    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_config] = lambda: default_config
    app.dependency_overrides[fix_dependencies] = lambda: fix_deps
    return app


@pytest.fixture
async def api_client(fast_api: FastAPI) -> AsyncIterator[AsyncClient]:  # noqa: F811
    async with AsyncClient(app=fast_api, base_url="http://test") as ac:
        yield ac
