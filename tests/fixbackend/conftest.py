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
import os
from argparse import Namespace
from asyncio import AbstractEventLoop
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterator, List, Sequence, Tuple, Optional
from unittest.mock import patch

import pytest
from alembic.command import upgrade as alembic_upgrade, check as alembic_check
from alembic.config import Config as AlembicConfig
from arq import ArqRedis, create_pool
from arq.connections import RedisSettings
from attrs import frozen
from boto3 import Session as BotoSession
from fastapi import FastAPI
from fixcloudutils.redis.pub_sub import RedisPubSubPublisher
from fixcloudutils.types import Json, JsonElement
from httpx import AsyncClient, MockTransport, Request, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy_utils import create_database, database_exists, drop_database

from fixbackend.analytics import AnalyticsEventSender
from fixbackend.analytics.analytics_event_sender import NoAnalyticsEventSender
from fixbackend.app import fast_api_app
from fixbackend.auth.models import User
from fixbackend.auth.user_repository import get_user_repository, UserRepository
from fixbackend.cloud_accounts.repository import CloudAccountRepository, CloudAccountRepositoryImpl
from fixbackend.collect.collect_queue import RedisCollectQueue
from fixbackend.config import Config, get_config
from fixbackend.db import get_async_session, get_async_session_maker
from fixbackend.dependencies import FixDependencies, ServiceNames, fix_dependencies
from fixbackend.dispatcher.dispatcher_service import DispatcherService
from fixbackend.dispatcher.next_run_repository import NextRunRepository
from fixbackend.domain_events.events import Event
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.domain_events.subscriber import DomainEventSubscriber
from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import SubscriptionId
from fixbackend.inventory.inventory_client import InventoryClient
from fixbackend.inventory.inventory_service import InventoryService
from fixbackend.metering.metering_repository import MeteringRepository
from fixbackend.notification.email.email_sender import EmailSender
from fixbackend.notification.service import NotificationService
from fixbackend.subscription.aws_marketplace import AwsMarketplaceHandler
from fixbackend.subscription.billing import BillingService
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.types import AsyncSessionMaker
from fixbackend.utils import start_of_next_month, uid
from fixbackend.workspaces.invitation_repository import InvitationRepository, InvitationRepositoryImpl
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository, WorkspaceRepositoryImpl

DATABASE_URL = "mysql+aiomysql://root@127.0.0.1:3306/fixbackend-testdb"
# only used to create/drop the database
SYNC_DATABASE_URL = "mysql+pymysql://root@127.0.0.1:3306/fixbackend-testdb"
RequestHandlerMock = List[Callable[[Request], Awaitable[Response]]]
os.environ["LOCAL_DEV_ENV"] = "true"


@pytest.fixture(scope="session")
def event_loop() -> Iterator[AbstractEventLoop]:
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def default_config() -> Config:
    return Config(
        environment="test",
        instance_id="test",
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
        redis_temp_store_url="redis://localhost:6379/1",
        redis_queue_url="redis://localhost:6379/5",
        cdn_endpoint="",
        cdn_bucket="",
        fixui_sha="",
        static_assets=None,
        session_ttl=3600,
        available_db_server=["http://localhost:8529", "http://127.0.0.1:8529"],
        inventory_url="http://localhost:8980",
        cf_template_url="dev-eu",
        args=Namespace(dispatcher=False, mode="app"),
        aws_access_key_id="",
        aws_secret_access_key="",
        aws_region="",
        ca_cert=None,
        host_cert=None,
        host_key=None,
        signing_cert_1=None,
        signing_key_1=None,
        signing_cert_2=None,
        signing_key_2=None,
        customerio_baseurl="",
        customerio_site_id=None,
        customerio_api_key=None,
        cloud_account_service_event_parallelism=1000,
        aws_cf_stack_notification_sqs_url=None,
        oauth_state_token_ttl=3600,
        profiling_enabled=False,
        profiling_interval=42,
        google_analytics_measurement_id=None,
        google_analytics_api_secret=None,
        aws_marketplace_url="",
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
    project_folder = Path(__file__).parent.parent.parent
    alembic_config = AlembicConfig((project_folder / "alembic.ini").absolute())
    alembic_config.set_main_option("script_location", str((project_folder / "migrations").absolute()))
    alembic_config.set_main_option("sqlalchemy.url", DATABASE_URL)
    await asyncio.to_thread(alembic_upgrade, alembic_config, "head")  # noqa
    await asyncio.to_thread(alembic_check, alembic_config)  # noqa

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
async def boto_answers() -> Dict[str, Any]:
    return {}


@pytest.fixture
async def boto_requests() -> List[Tuple[str, Any]]:
    return []


@pytest.fixture
async def boto_session(
    boto_answers: Dict[str, Any], boto_requests: List[Tuple[str, Any]]
) -> AsyncIterator[BotoSession]:
    def mock_make_api_call(client: Any, operation_name: str, kwarg: Any) -> Any:
        boto_requests.append((operation_name, kwarg))
        if result := boto_answers.get(operation_name):
            return result
        else:
            raise Exception(f"Please provide mocked answer for boto operation {operation_name} and arguments {kwarg}")

    with patch("botocore.client.BaseClient._make_api_call", new=mock_make_api_call):
        yield BotoSession(region_name="us-east-1")


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
async def user_repository(async_session_maker: AsyncSessionMaker) -> UserRepository:
    repo = await anext(get_user_repository(async_session_maker))
    return repo


@pytest.fixture
async def user(async_session_maker: AsyncSessionMaker) -> User:
    user_repository = await anext(get_user_repository(async_session_maker))
    user_dict = {
        "email": "foo@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    return await user_repository.create(user_dict)


@pytest.fixture
async def workspace(workspace_repository: WorkspaceRepository, user: User) -> Workspace:
    return await workspace_repository.create_workspace("foo", "foo", user)


@pytest.fixture
async def graph_db_access(
    workspace: Workspace, graph_database_access_manager: GraphDatabaseAccessManager
) -> GraphDatabaseAccess:
    if access := await graph_database_access_manager.get_database_access(workspace.id):
        return access
    else:
        return await graph_database_access_manager.create_database_access(workspace.id)


@pytest.fixture
async def subscription(
    subscription_repository: SubscriptionRepository, user: User, workspace: Workspace
) -> AwsMarketplaceSubscription:
    return await subscription_repository.create(
        AwsMarketplaceSubscription(
            id=SubscriptionId(uid()),
            user_id=user.id,
            workspace_id=workspace.id,
            customer_identifier="123",
            customer_aws_account_id="123456789",
            product_code="foo",
            active=True,
            last_charge_timestamp=datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            next_charge_timestamp=start_of_next_month(hour=9),
        )
    )


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
async def redis() -> AsyncIterator[Redis]:
    redis = Redis.from_url("redis://localhost:6379/6", decode_responses=True)
    keys = await redis.keys()
    if keys:
        await redis.delete(*keys)
    yield redis
    await redis.close()


@pytest.fixture
async def domain_event_subscriber(redis: Redis, default_config: Config) -> DomainEventSubscriber:
    return DomainEventSubscriber(redis, default_config, "test-subscriber")


@pytest.fixture
async def collect_queue(arq_redis: ArqRedis) -> RedisCollectQueue:
    return RedisCollectQueue(arq_redis)


@pytest.fixture
def benchmark_json() -> List[Json]:
    return [
        {"id": "a", "type": "node", "reported": {"kind": "report_benchmark", "name": "benchmark_name"}},
        {"id": "b", "type": "node", "reported": {"kind": "report_check_result", "title": "Something"}},
        {"from": "a", "to": "b", "type": "edge", "edge_type": "default"},
    ]


@pytest.fixture
def aws_ec2_model_json() -> Json:
    return {
        "type": "object",
        "fqn": "aws_ec2_instance",
        "bases": ["aws_resource", "instance", "resource"],
        "allow_unknown_props": False,
        "predecessor_kinds": {"default": ["aws_elb"], "delete": []},
        "successor_kinds": {"default": ["aws_ec2_volume"], "delete": []},
        "aggregate_root": True,
        "metadata": {"icon": "instance", "group": "compute"},
        "properties": {"id": {"kind": {"type": "simple", "fqn": "string"}, "required": False}},
    }


@pytest.fixture
def azure_virtual_machine_resource_json() -> Json:
    return {
        "id": "some_node_id",
        "type": "node",
        "revision": "_g1sTwKq--_",
        "reported": {
            "id": "/subscriptions/test/resourceGroups/foo/providers/Microsoft.Compute/virtualMachines/test",
            "kind": "azure_virtual_machine",
            "tags": {"foo": "bla"},
            "name": "test",
            "instance_cores": 5,
            "instance_memory": 1024,
            "instance_type": "Standard_B1ls",
            "instance_status": "running",
            "ctime": "2023-07-10T16:25:09Z",
            "vm_id": "de2afccb-585d-48cd-a68e-fb6f20639084",
            "age": "3mo27d",
        },
        "ancestors": {
            "cloud": {"reported": {"name": "azure", "id": "azure"}},
            "account": {"reported": {"name": "/subscriptions/test", "id": "/subscriptions/test"}},
            "region": {"reported": {"name": "westeurope", "id": "/subscriptions/test/locations/westeurope"}},
        },
        "security": {
            "issues": [
                {
                    "benchmark": "azure_cis_1_1_1",
                    "check": "aws_c1",
                    "severity": "medium",
                    "opened_at": "2023-11-15T15:44:41Z",
                    "run_id": "foo",
                }
            ],
            "opened_at": "2023-11-15T15:44:41Z",
            "reopen_counter": 1,
            "run_id": "foo",
            "has_issues": True,
            "severity": "medium",
        },
    }


def json_response(content: JsonElement, additional_headers: Optional[Dict[str, str]] = None) -> Response:
    return Response(
        200,
        content=json.dumps(content).encode("utf-8"),
        headers={"content-type": "application/json", **(additional_headers or {})},
    )


def nd_json_response(content: Sequence[JsonElement]) -> Response:
    response = ""
    for a in content:
        response += json.dumps(a) + "\n"
    return Response(200, content=response.encode("utf-8"), headers={"content-type": "application/x-ndjson"})


@pytest.fixture
async def request_handler_mock() -> RequestHandlerMock:
    return []


@pytest.fixture
async def inventory_requests() -> List[Request]:
    return []


@pytest.fixture
async def http_client(request_handler_mock: RequestHandlerMock, inventory_requests: List[Request]) -> AsyncClient:
    async def app(request: Request) -> Response:
        inventory_requests.append(request)
        for mock in request_handler_mock:
            try:
                return await mock(request)
            except AttributeError:
                pass
        raise AttributeError(f'Unexpected request: {request.url.path} with content {request.content.decode("utf-8")}')

    return AsyncClient(transport=MockTransport(app))


@pytest.fixture
def analytics_event_sender() -> AnalyticsEventSender:
    return NoAnalyticsEventSender()


@pytest.fixture
async def inventory_client(
    http_client: AsyncClient, request_handler_mock: RequestHandlerMock
) -> AsyncIterator[InventoryClient]:
    async with InventoryClient("http://localhost:8980", client=http_client) as client:
        yield client


@pytest.fixture
async def inventory_service(
    inventory_client: InventoryClient,
    graph_database_access_manager: GraphDatabaseAccessManager,
    domain_event_subscriber: DomainEventSubscriber,
    redis: Redis,
) -> AsyncIterator[InventoryService]:
    async with InventoryService(
        inventory_client, graph_database_access_manager, domain_event_subscriber, redis
    ) as service:
        yield service


@pytest.fixture
async def next_run_repository(async_session_maker: AsyncSessionMaker) -> NextRunRepository:
    return NextRunRepository(async_session_maker)


@pytest.fixture
async def cloud_account_repository(async_session_maker: AsyncSessionMaker) -> CloudAccountRepository:
    return CloudAccountRepositoryImpl(async_session_maker)


@pytest.fixture
async def subscription_repository(async_session_maker: AsyncSessionMaker) -> SubscriptionRepository:
    return SubscriptionRepository(async_session_maker)


@pytest.fixture
async def metering_repository(async_session_maker: AsyncSessionMaker) -> MeteringRepository:
    return MeteringRepository(async_session_maker)


class InMemoryDomainEventPublisher(DomainEventPublisher):
    def __init__(self) -> None:
        self.events: List[Event] = []

    async def publish(self, event: Event) -> None:
        self.events.append(event)


@pytest.fixture
async def domain_event_sender() -> InMemoryDomainEventPublisher:
    return InMemoryDomainEventPublisher()


@frozen
class PubSubMessage:
    kind: str
    message: Json
    channel: Optional[str]


class InMemoryRedisPubSubPublisher(RedisPubSubPublisher):
    # noinspection PyMissingConstructor
    def __init__(self) -> None:
        self.events: List[PubSubMessage] = []

    async def publish(self, kind: str, message: Json, channel: Optional[str] = None) -> None:
        self.events.append(PubSubMessage(kind, message, channel))


@pytest.fixture
def pubsub_publisher() -> InMemoryRedisPubSubPublisher:
    return InMemoryRedisPubSubPublisher()


@pytest.fixture
async def workspace_repository(
    async_session_maker: AsyncSessionMaker,
    graph_database_access_manager: GraphDatabaseAccessManager,
    domain_event_sender: DomainEventPublisher,
    pubsub_publisher: InMemoryRedisPubSubPublisher,
    subscription_repository: SubscriptionRepository,
) -> WorkspaceRepository:
    return WorkspaceRepositoryImpl(
        async_session_maker,
        graph_database_access_manager,
        domain_event_sender,
        pubsub_publisher,
        subscription_repository,
    )


@pytest.fixture
async def invitation_repository(
    async_session_maker: AsyncSessionMaker,
    workspace_repository: WorkspaceRepository,
    user_repository: UserRepository,
) -> InvitationRepository:
    return InvitationRepositoryImpl(async_session_maker, workspace_repository, user_repository)


@pytest.fixture
async def aws_marketplace_handler(
    subscription_repository: SubscriptionRepository,
    metering_repository: MeteringRepository,
    workspace_repository: WorkspaceRepository,
    boto_session: BotoSession,
) -> AwsMarketplaceHandler:
    return AwsMarketplaceHandler(subscription_repository, workspace_repository, metering_repository, boto_session, None)


@pytest.fixture
async def dispatcher(
    arq_redis: ArqRedis,
    cloud_account_repository: CloudAccountRepository,
    next_run_repository: NextRunRepository,
    metering_repository: MeteringRepository,
    collect_queue: RedisCollectQueue,
    graph_database_access_manager: GraphDatabaseAccessManager,
    domain_event_sender: DomainEventPublisher,
    domain_event_subscriber: DomainEventSubscriber,
    workspace_repository: WorkspaceRepository,
    redis: Redis,
) -> DispatcherService:
    return DispatcherService(
        arq_redis,
        cloud_account_repository,
        next_run_repository,
        metering_repository,
        collect_queue,
        graph_database_access_manager,
        domain_event_sender,
        redis,
        domain_event_subscriber,
        workspace_repository,
    )


@pytest.fixture
async def fix_deps(
    db_engine: AsyncEngine,
    graph_database_access_manager: GraphDatabaseAccessManager,
    async_session_maker: AsyncSessionMaker,
    workspace_repository: WorkspaceRepository,
) -> FixDependencies:
    return FixDependencies(
        **{
            ServiceNames.async_engine: db_engine,
            ServiceNames.graph_db_access: graph_database_access_manager,
            ServiceNames.session_maker: async_session_maker,
            ServiceNames.workspace_repo: workspace_repository,
        }
    )


# noinspection PyUnresolvedReferences
@pytest.fixture
async def fast_api(
    fix_deps: FixDependencies, session: AsyncSession, default_config: Config, async_session_maker: AsyncSessionMaker
) -> FastAPI:
    app: FastAPI = fast_api_app(default_config)
    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_async_session_maker] = lambda: async_session_maker
    app.dependency_overrides[get_config] = lambda: default_config
    app.dependency_overrides[fix_dependencies] = lambda: fix_deps
    return app


@pytest.fixture
async def api_client(fast_api: FastAPI) -> AsyncIterator[AsyncClient]:  # noqa: F811
    async with AsyncClient(app=fast_api, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def billing_service(
    aws_marketplace_handler: AwsMarketplaceHandler,
    subscription_repository: SubscriptionRepository,
    workspace_repository: WorkspaceRepository,
) -> BillingService:
    return BillingService(aws_marketplace_handler, subscription_repository, workspace_repository)


@frozen
class NotificationEmail:
    to: List[str]
    subject: str
    text: str
    html: Optional[str]


class InMemoryEmailSender(EmailSender):
    def __init__(self) -> None:
        self.call_args: List[NotificationEmail] = []

    async def send_email(self, *, to: List[str], subject: str, text: str, html: str | None) -> None:
        self.call_args.append(NotificationEmail(to, subject, text, html))


@pytest.fixture
def email_sender() -> InMemoryEmailSender:
    return InMemoryEmailSender()


@pytest.fixture
def notification_service(
    default_config: Config,
    graph_database_access_manager: GraphDatabaseAccessManager,
    workspace_repository: WorkspaceRepository,
    user_repository: UserRepository,
    inventory_service: InventoryService,
    redis: Redis,
    email_sender: EmailSender,
    async_session_maker: AsyncSessionMaker,
) -> NotificationService:
    service = NotificationService(
        default_config,
        workspace_repository,
        graph_database_access_manager,
        user_repository,
        inventory_service,
        redis,
        async_session_maker,
    )
    service.email_sender = email_sender
    return service
