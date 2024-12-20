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
import hashlib
import json
import os
import random
from argparse import Namespace
from asyncio import AbstractEventLoop
from contextlib import suppress
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    Iterator,
    List,
    Sequence,
    Tuple,
    Optional,
    Unpack,
    Union,
)
from unittest.mock import patch

import jwt
import pytest
import stripe
from alembic.command import upgrade as alembic_upgrade, check as alembic_check
from alembic.config import Config as AlembicConfig
from arq import ArqRedis, create_pool
from arq.connections import RedisSettings
from async_lru import alru_cache
from attrs import frozen
from boto3 import Session as BotoSession
from fastapi import FastAPI
from fastapi_users.password import PasswordHelper
from fixcloudutils.asyncio.process_pool import AsyncProcessPool
from fixcloudutils.redis.event_stream import RedisStreamPublisher
from fixcloudutils.redis.pub_sub import RedisPubSubPublisher
from fixcloudutils.types import Json, JsonElement
from fixcloudutils.util import utc
from httpx import AsyncClient, MockTransport, Request, Response
from sqlalchemy import NullPool, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy_utils import create_database, database_exists, drop_database

from fixbackend.analytics import AnalyticsEventSender
from fixbackend.analytics.events import AnalyticsEvent
from fixbackend.app import fast_api_app
from fixbackend.auth.api_token_service import ApiTokenService
from fixbackend.auth.auth_backend import FixJWTStrategy
from fixbackend.auth.models import User
from fixbackend.auth.user_repository import get_user_repository, UserRepository
from fixbackend.billing.billing_job import BillingJob
from fixbackend.billing.service import BillingEntryService
from fixbackend.certificates.cert_store import CertificateStore
from fixbackend.cloud_accounts.azure_subscription_repo import AzureSubscriptionCredentialsRepository
from fixbackend.cloud_accounts.azure_subscription_service import AzureSubscriptionService, SubscriptionInfo
from fixbackend.cloud_accounts.gcp_service_account_repo import GcpServiceAccountKeyRepository
from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.cloud_accounts.gcp_service_account_service import GcpServiceAccountService
from fixbackend.collect.collect_queue import RedisCollectQueue
from fixbackend.config import Config, get_config
from fixbackend.db import get_async_session, get_async_session_maker
from fixbackend.dependencies import FixDependencies, ServiceNames, fix_dependencies
from fixbackend.dispatcher.dispatcher_service import DispatcherService
from fixbackend.dispatcher.next_run_repository import NextRunRepository
from fixbackend.domain_events.events import Event
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.domain_events.subscriber import DomainEventSubscriber
from fixbackend.fix_jwt import JwtService
from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import (
    AzureSubscriptionCredentialsId,
    GcpServiceAccountKeyId,
    ReportSeverity,
    SubscriptionId,
    WorkspaceId,
    BenchmarkName,
    NodeId,
    UserId,
    StripeCustomerId,
    StripeSubscriptionId,
    BillingPeriod,
    ProductTier,
)
from fixbackend.inventory.inventory_client import InventoryClient
from fixbackend.inventory.inventory_service import InventoryService
from fixbackend.metering.metering_repository import MeteringRepository
from fixbackend.notification.email.email_sender import EmailSender
from fixbackend.notification.model import FailingBenchmarkChecksDetected, FailedBenchmarkCheck, VulnerableResource
from fixbackend.notification.notification_service import NotificationService
from fixbackend.notification.user_notification_repo import UserNotificationSettingsRepository
from fixbackend.permissions.role_repository import RoleRepository
from fixbackend.subscription.aws_marketplace import AwsMarketplaceHandler
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.subscription.stripe_subscription import StripeServiceImpl, StripeClient
from fixbackend.subscription.subscription_repository import AwsTierPreferenceRepository, SubscriptionRepository
from fixbackend.types import AsyncSessionMaker
from fixbackend.types import Redis
from fixbackend.utils import start_of_next_month, uid
from fixbackend.workspaces.invitation_repository import InvitationRepository
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository

DATABASE_URL = "postgresql+asyncpg://fix@127.0.0.1:5432/fixbackend-testdb"
# only used to create/drop the database
SYNC_DATABASE_URL = "postgresql+psycopg://fix@127.0.0.1:5432/fixbackend-testdb"
RequestHandlerMock = List[Callable[[Request], Awaitable[Response]]]
os.environ["LOCAL_DEV_ENV"] = "true"


async def eventually(
    fn: Callable[[], Union[bool, Awaitable[bool]]],
    timeout: float = 10,
    interval: float = 0.1,
) -> None:
    deadline = utc() + timedelta(seconds=timeout)
    while True:
        with suppress(Exception):
            res = fn()
            if isinstance(res, Awaitable):
                res = await res
            if res:
                return
        if datetime.now(timezone.utc) > deadline:
            raise TimeoutError(f"Timeout after {timeout} seconds")
        await asyncio.sleep(interval)


class RedisStreamPublisherMock(RedisStreamPublisher):
    # noinspection PyMissingConstructor
    def __init__(self) -> None:
        self.messages: List[Tuple[str, Json]] = []
        self.last_message: Optional[Tuple[str, Json]] = None

    async def publish(self, kind: str, message: Json) -> None:
        self.messages.append((kind, message))
        self.last_message = (kind, message)


class RedisPubSubPublisherMock(RedisPubSubPublisher):
    # noinspection PyMissingConstructor
    def __init__(self) -> None:
        self.messages: List[Tuple[str, Json, Optional[str]]] = []
        self.last_message: Optional[Tuple[str, Json, Optional[str]]] = None

    async def publish(self, kind: str, message: Json, channel: Optional[str] = None) -> None:
        self.messages.append((kind, message, channel))
        self.last_message = (kind, message, channel)


@pytest.fixture
def redis_publisher_mock() -> RedisPubSubPublisherMock:
    return RedisPubSubPublisherMock()


@pytest.fixture(scope="session")
def event_loop() -> Iterator[AbstractEventLoop]:
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def default_config() -> Config:
    return Config(
        environment="dev",
        instance_id="test",
        database_name="fixbackend-testdb",
        database_user="fix",
        database_password=None,
        database_host="127.0.0.1",
        database_port=5432,
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
        args=Namespace(dispatcher=False, mode="app", redis_password=None, aws_marketplace_metering_sqs_url=None),
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
        cloud_account_service_event_parallelism=1000,
        aws_cf_stack_notification_sqs_url=None,
        oauth_state_token_ttl=3600,
        profiling_enabled=False,
        profiling_interval=42,
        google_analytics_measurement_id=None,
        google_analytics_api_secret=None,
        aws_marketplace_url="",
        billing_period="month",
        discord_oauth_client_id="",
        discord_oauth_client_secret="",
        slack_oauth_client_id="",
        slack_oauth_client_secret="",
        service_base_url="http://localhost:8000",
        support_base_url="http://localhost:8000",
        push_gateway_url=None,
        posthog_api_key=None,
        stripe_api_key=None,
        stripe_webhook_key=None,
        customer_support_users=[],
        free_tier_cleanup_timeout_days=7,
        azure_client_id="",
        azure_client_secret="",
        azure_tenant_id="",
        account_failed_resource_count=1,
        degraded_accounts_ping_interval_hours=24,
        auth_rate_limit_per_minute=100,
    )


@pytest.fixture
async def async_process_pool() -> AsyncIterator[AsyncProcessPool]:
    async with AsyncProcessPool() as pool:
        yield pool


@pytest.fixture(scope="session")
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """
    Creates a new database for a test and runs the migrations.
    """
    no_db_drop = os.environ.get("NO_DB_DROP", "False").lower() == "true"
    # make sure the db exists and it is clean
    if database_exists(SYNC_DATABASE_URL) and not no_db_drop:
        drop_database(SYNC_DATABASE_URL)
    if not database_exists(SYNC_DATABASE_URL):
        create_database(SYNC_DATABASE_URL)

    while not database_exists(SYNC_DATABASE_URL):
        await asyncio.sleep(0.1)

    engine = create_async_engine(DATABASE_URL, isolation_level="SERIALIZABLE", poolclass=NullPool)
    project_folder = Path(__file__).parent.parent.parent
    alembic_config = AlembicConfig((project_folder / "alembic.ini").absolute())
    alembic_config.set_main_option("script_location", str((project_folder / "migrations").absolute()))
    alembic_config.set_main_option("sqlalchemy.url", DATABASE_URL)
    await asyncio.to_thread(alembic_upgrade, alembic_config, "head")  # noqa
    await asyncio.to_thread(alembic_check, alembic_config)  # noqa

    tables_to_truncate: List[str] = []
    if no_db_drop and tables_to_truncate:
        async with engine.connect() as conn:
            for table in tables_to_truncate:
                await conn.execute(text(f"TRUNCATE TABLE {table}"))

    yield engine

    await engine.dispose()
    if not no_db_drop:
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
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
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
async def aws_marketplace_subscription(
    subscription_repository: SubscriptionRepository, user: User
) -> AwsMarketplaceSubscription:
    return await subscription_repository.create(
        AwsMarketplaceSubscription(
            id=SubscriptionId(uid()),
            user_id=user.id,
            customer_identifier="123",
            customer_aws_account_id="123456789",
            product_code="foo",
            active=True,
            last_charge_timestamp=datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            next_charge_timestamp=start_of_next_month(hour=9),
        )
    )


@pytest.fixture
async def arq_redis_settings() -> RedisSettings:
    return RedisSettings(host="localhost", port=6379, database=5)


@pytest.fixture
async def arq_redis(arq_redis_settings: RedisSettings) -> AsyncIterator[ArqRedis]:
    redis = await create_pool(arq_redis_settings)
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


def fake_account(
    account_id: str,
    cloud_name: str,
) -> Json:

    benchmark = {
        "iso27001": {
            "score": 76,
            "failed": {
                "critical": {"checks": 3, "resources": 6},
                "medium": {"checks": 14, "resources": 18},
                "high": {"checks": 3, "resources": 3},
                "info": {"checks": 2, "resources": 8},
            },
        },
        "gcp_test": {
            "score": 70,
            "failed": {
                "high": {"checks": 1, "resources": 1},
                "medium": {"checks": 15, "resources": 19},
                "info": {"checks": 2, "resources": 8},
                "critical": {"checks": 2, "resources": 2},
            },
        },
        "aws_test": {
            "score": 89,
            "failed": {
                "medium": {"checks": 6, "resources": 10},
                "low": {"checks": 2, "resources": 8},
                "high": {"checks": 1, "resources": 1},
                "info": {"checks": 1, "resources": 4},
            },
        },
        "aws_cis_1_5": {
            "score": 89,
            "failed": {
                "medium": {"checks": 6, "resources": 10},
                "low": {"checks": 2, "resources": 8},
                "high": {"checks": 1, "resources": 1},
                "info": {"checks": 1, "resources": 4},
            },
        },
        "aws_well_architected_framework_security_pillar": {
            "score": 85,
            "failed": {
                "high": {"checks": 5, "resources": 8},
                "low": {"checks": 3, "resources": 12},
                "medium": {"checks": 29, "resources": 39},
                "info": {"checks": 2, "resources": 8},
            },
        },
    }

    if cloud_name == "aws":
        del benchmark["gcp_test"]

    if cloud_name == "gcp":
        del benchmark["aws_test"]

    return {
        "id": "CbkG1xZX2-HXjrdMIrX4OQ",
        "type": "node",
        "revision": "_iRG9vXm---",
        "reported": {
            "id": account_id,
            "name": f"{cloud_name} account",
        },
        "security": {
            "has_issues": True,
            "issues": [
                {
                    "check": "aws_iam_password_policy_expire_90",
                    "severity": "high",
                    "opened_at": "2024-05-06T12:06:12Z",
                    "benchmarks": ["iso27001", "nis-2", "aws_well_architected_framework_security_pillar"],
                },
                {
                    "check": "aws_c1",
                    "severity": "medium",
                    "opened_at": "2024-07-31T03:42:50Z",
                    "benchmarks": [
                        "nis-2",
                        "aws_well_architected_framework_security_pillar",
                        "aws_cis_1_5",
                        "aws_test",
                        "iso27001",
                    ],
                },
                {
                    "check": "aws_cloudwatch_changes_to_vpcs_alarm_configured",
                    "severity": "medium",
                    "opened_at": "2024-06-24T13:53:30Z",
                    "benchmarks": [
                        "iso27001",
                        "gcp_test",
                    ],
                },
                {
                    "check": "aws_cloudwatch_changes_to_route_table_alarm_configured",
                    "severity": "medium",
                    "opened_at": "2024-06-24T13:53:30Z",
                    "benchmarks": ["iso27001", "nis-2"],
                },
                {
                    "check": "aws_cloudwatch_changes_to_internet_gateway_alarm_configured",
                    "severity": "medium",
                    "opened_at": "2024-06-24T13:53:30Z",
                    "benchmarks": ["iso27001", "nis-2"],
                },
                {
                    "check": "aws_cloudwatch_changes_to_network_acl_alarm_configured",
                    "severity": "medium",
                    "opened_at": "2024-06-24T13:53:30Z",
                    "benchmarks": ["iso27001", "nis-2"],
                },
                {
                    "check": "aws_cloudwatch_changes_to_s3_bucket_policy_alarm_configured",
                    "severity": "medium",
                    "opened_at": "2024-06-24T13:53:30Z",
                    "benchmarks": ["iso27001", "nis-2"],
                },
                {
                    "check": "aws_cloudwatch_cross_account_sharing_enabled",
                    "severity": "medium",
                    "opened_at": "2024-07-31T03:42:50Z",
                    "benchmarks": ["aws_well_architected_framework_security_pillar"],
                },
            ],
            "severity": "high",
        },
        "metadata": {
            "benchmark": benchmark,
            "categories": [],
            "cleaned": False,
            "descendant_count": 265,
            "descendant_summary": {
                "aws_s3_bucket": 4,
                "aws_iam_instance_profile": 1,
                "aws_cloudfront_cache_policy": 11,
                "aws_cloudfront_response_headers_policy": 5,
                "aws_root_user": 1,
                "aws_iam_role": 26,
                "aws_iam_policy": 20,
                "aws_ec2_instance": 1,
                "aws_ec2_network_interface": 3,
                "aws_ec2_volume": 2,
                "aws_ec2_route_table": 19,
                "aws_vpc": 18,
                "aws_ec2_security_group": 20,
                "aws_ec2_internet_gateway": 18,
                "aws_ec2_network_acl": 18,
                "aws_ec2_subnet": 57,
                "aws_athena_work_group": 17,
                "aws_cloudformation_stack": 10,
                "aws_cloudwatch_log_group": 3,
                "aws_lambda_function": 2,
                "aws_ec2_keypair": 1,
                "aws_alb": 1,
                "aws_rds_instance": 1,
                "aws_rds_snapshot": 4,
                "aws_ssm_instance": 1,
                "aws_dynamodb_table": 1,
            },
            "exported_at": "2024-08-08T13:44:30Z",
            "failed": {
                "high": {"checks": 4, "resources": 7},
                "medium": {"checks": 22, "resources": 33},
                "critical": {"checks": 3, "resources": 6},
                "info": {"checks": 1, "resources": 4},
                "low": {"checks": 3, "resources": 12},
            },
            "phantom": False,
            "protected": False,
            "python_type": "fix_plugin_aws.resource.base.AwsAccount",
            "replace": True,
            "score": 81.8,
            "exported_age": "35min11s",
        },
        "ancestors": {
            "cloud": {"reported": {"name": cloud_name, "id": cloud_name}},
            "account": {"reported": {"name": f"{cloud_name} account", "id": account_id}},
        },
    }


@pytest.fixture
def accounts_json() -> List[Json]:
    return [fake_account("123", "aws"), fake_account("234", "gcp")]


@pytest.fixture
def example_check() -> Json:
    return {
        "categories": [],
        "detect": {"fix": "is(aws_s3_bucket)"},
        "id": "aws_c1",
        "provider": "aws",
        "remediation": {
            "kind": "fix_core_report_check_remediation",
            "text": "You can enable Public Access Block at the account level to prevent the exposure of your data stored in S3.",
            "url": "https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html",
        },
        "result_kind": "aws_s3_bucket",
        "risk": "Public access policies may be applied to sensitive data buckets.",
        "service": "s3",
        "severity": "high",
        "title": "Check S3 Account Level Public Access Block.",
    }


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


@pytest.fixture
def alert_failing_benchmark_checks_detected() -> FailingBenchmarkChecksDetected:
    return FailingBenchmarkChecksDetected(
        "some_id",
        WorkspaceId(uid()),
        BenchmarkName("benchmark_name"),
        ReportSeverity.critical,
        23,
        [
            FailedBenchmarkCheck(
                "example_check",
                "Title of check",
                ReportSeverity.critical,
                12,
                [
                    VulnerableResource(NodeId("id1"), "test_resource_1", "some_name_1", ui_link="https://fix.tt/1"),
                    VulnerableResource(NodeId("id2"), "test_resource_2", "some_name_2", ui_link="https://fix.tt/2"),
                    VulnerableResource(NodeId("id3"), "test_resource_3", "some_name_3", ui_link="https://fix.tt/3"),
                    VulnerableResource(NodeId("id4"), "test_resource_4", "some_name_4", ui_link="https://fix.tt/4"),
                ],
            )
        ],
        "https://fix.security/",
    )


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
async def success_handler_mock(request_handler_mock: RequestHandlerMock) -> RequestHandlerMock:
    async def always_success(_: Request) -> Response:
        return Response(204)

    request_handler_mock.append(always_success)
    return request_handler_mock


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


class InMemoryAnalyticsEventSender(AnalyticsEventSender):
    def __init__(self) -> None:
        self.events: List[AnalyticsEvent] = []

    async def send(self, event: AnalyticsEvent) -> None:
        self.events.append(event)

    async def user_id_from_workspace(self, workspace_id: WorkspaceId) -> UserId:
        return UserId(uid())


@pytest.fixture
def analytics_event_sender() -> InMemoryAnalyticsEventSender:
    return InMemoryAnalyticsEventSender()


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
    cloud_account_repository: CloudAccountRepository,
    redis: Redis,
    arq_redis_settings: RedisSettings,
) -> AsyncIterator[InventoryService]:
    async with InventoryService(
        inventory_client,
        graph_database_access_manager,
        cloud_account_repository,
        domain_event_subscriber,
        redis,
        arq_redis_settings,
    ) as service:
        yield service


@pytest.fixture
async def next_run_repository(async_session_maker: AsyncSessionMaker) -> NextRunRepository:
    return NextRunRepository(async_session_maker)


@pytest.fixture
async def cloud_account_repository(async_session_maker: AsyncSessionMaker) -> CloudAccountRepository:
    return CloudAccountRepository(async_session_maker)


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
async def role_repository(
    async_session_maker: AsyncSessionMaker,
) -> RoleRepository:
    return RoleRepository(async_session_maker)


@pytest.fixture
async def workspace_repository(
    async_session_maker: AsyncSessionMaker,
    graph_database_access_manager: GraphDatabaseAccessManager,
    domain_event_sender: DomainEventPublisher,
    pubsub_publisher: InMemoryRedisPubSubPublisher,
    subscription_repository: SubscriptionRepository,
    role_repository: RoleRepository,
) -> WorkspaceRepository:
    return WorkspaceRepository(
        async_session_maker,
        graph_database_access_manager,
        domain_event_sender,
        pubsub_publisher,
        subscription_repository,
        role_repository,
    )


@pytest.fixture
async def invitation_repository(
    async_session_maker: AsyncSessionMaker,
    workspace_repository: WorkspaceRepository,
    user_repository: UserRepository,
) -> InvitationRepository:
    return InvitationRepository(async_session_maker, workspace_repository, user_repository)


@pytest.fixture
async def billing_entry_service(
    subscription_repository: SubscriptionRepository,
    workspace_repository: WorkspaceRepository,
    metering_repository: MeteringRepository,
    domain_event_sender: DomainEventPublisher,
    default_config: Config,
    cloud_account_repository: CloudAccountRepository,
) -> BillingEntryService:
    return BillingEntryService(
        subscription_repository,
        workspace_repository,
        metering_repository,
        domain_event_sender,
        default_config.billing_period,
        cloud_account_repository,
    )


@pytest.fixture
async def aws_marketplace_handler(
    subscription_repository: SubscriptionRepository,
    metering_repository: MeteringRepository,
    workspace_repository: WorkspaceRepository,
    boto_session: BotoSession,
    domain_event_sender: DomainEventPublisher,
    billing_entry_service: BillingEntryService,
    async_session_maker: AsyncSessionMaker,
) -> AwsMarketplaceHandler:
    return AwsMarketplaceHandler(
        subscription_repository,
        workspace_repository,
        boto_session,
        domain_event_sender,
        billing_entry_service,
        None,
        AwsTierPreferenceRepository(async_session_maker),
    )


@pytest.fixture
def gcp_service_account_key_repo(async_session_maker: AsyncSessionMaker) -> GcpServiceAccountKeyRepository:
    return GcpServiceAccountKeyRepository(async_session_maker)


class GcpServiceAccountServiceMock(GcpServiceAccountService):

    def __init__(self) -> None:  # noqa
        pass

    async def start(self) -> Any:
        pass

    async def stop(self) -> None:
        pass

    async def list_projects(self, service_account_key: str) -> List[Dict[str, Any]]:
        return [{"projectId": "foo", "name": "bar"}]

    async def update_cloud_accounts(
        self, projects: List[Dict[str, Any]], tenant_id: WorkspaceId, key_id: GcpServiceAccountKeyId, only_new: bool
    ) -> None:
        return None


@pytest.fixture
def gcp_service_account_service() -> GcpServiceAccountService:
    return GcpServiceAccountServiceMock()


@pytest.fixture
def azure_subscription_credentials_repo(
    async_session_maker: AsyncSessionMaker,
) -> AzureSubscriptionCredentialsRepository:
    return AzureSubscriptionCredentialsRepository(async_session_maker)


class AzureSubscriptionServiceMock(AzureSubscriptionService):

    def __init__(self) -> None:  # noqa
        pass

    async def start(self) -> Any:
        return None

    async def stop(self) -> None:
        return None

    async def list_subscriptions(
        self, azure_tenant_id: str, client_id: str, client_secret: str
    ) -> List[SubscriptionInfo]:
        return []

    async def update_cloud_accounts(
        self,
        subscriptions: List[SubscriptionInfo],
        tenant_id: WorkspaceId,
        credentials_id: AzureSubscriptionCredentialsId,
    ) -> None:
        return None


@pytest.fixture
def azure_subscription_service() -> AzureSubscriptionService:
    return AzureSubscriptionServiceMock()


@pytest.fixture
async def dispatcher(
    arq_redis: Redis,
    cloud_account_repository: CloudAccountRepository,
    next_run_repository: NextRunRepository,
    metering_repository: MeteringRepository,
    collect_queue: RedisCollectQueue,
    graph_database_access_manager: GraphDatabaseAccessManager,
    domain_event_sender: DomainEventPublisher,
    domain_event_subscriber: DomainEventSubscriber,
    workspace_repository: WorkspaceRepository,
    gcp_service_account_key_repo: GcpServiceAccountKeyRepository,
    azure_subscription_credentials_repo: AzureSubscriptionCredentialsRepository,
    redis: Redis,
    default_config: Config,
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
        gcp_service_account_key_repo,
        azure_subscription_credentials_repo,
        default_config,
    )


@pytest.fixture
async def cert_store(default_config: Config) -> CertificateStore:
    return CertificateStore(default_config)


class InsecureFastPasswordHelper(PasswordHelper):
    # noinspection PyMissingConstructor
    def __init__(self) -> None:
        pass

    def verify_and_update(self, plain_password: str, hashed_password: str) -> Tuple[bool, str]:
        return hashed_password == hashlib.md5(plain_password.encode()).hexdigest(), hashed_password

    def hash(self, password: str) -> str:
        return hashlib.md5(password.encode()).hexdigest()

    def generate(self) -> str:
        return str(random.randint(100000, 999999))


@pytest.fixture
def password_helper() -> InsecureFastPasswordHelper:
    return InsecureFastPasswordHelper()


@pytest.fixture
async def jwt_strategy(cert_store: CertificateStore) -> FixJWTStrategy:
    return FixJWTStrategy(cert_store, lifetime_seconds=3600)


@pytest.fixture
def api_token_service(
    async_session_maker: AsyncSessionMaker,
    workspace_repository: WorkspaceRepository,
    jwt_strategy: FixJWTStrategy,
    user_repository: UserRepository,
    async_process_pool: AsyncProcessPool,
) -> ApiTokenService:
    return ApiTokenService(async_session_maker, jwt_strategy, user_repository, workspace_repository, async_process_pool)


@pytest.fixture
async def fix_deps(
    default_config: Config,
    db_engine: AsyncEngine,
    graph_database_access_manager: GraphDatabaseAccessManager,
    async_session_maker: AsyncSessionMaker,
    workspace_repository: WorkspaceRepository,
    cert_store: CertificateStore,
    notification_service: NotificationService,
    domain_event_sender: DomainEventPublisher,
    invitation_repository: InvitationRepository,
    analytics_event_sender: AnalyticsEventSender,
    api_token_service: ApiTokenService,
    password_helper: InsecureFastPasswordHelper,
    jwt_strategy: FixJWTStrategy,
    gcp_service_account_key_repo: GcpServiceAccountKeyRepository,
    azure_subscription_credentials_repo: AzureSubscriptionCredentialsRepository,
    inventory_service: InventoryService,
    gcp_service_account_service: GcpServiceAccountService,
    azure_subscription_service: AzureSubscriptionService,
    jwt_service: JwtService,
    redis: Redis,
    user_repository: UserRepository,
) -> FixDependencies:
    # noinspection PyTestUnpassedFixture
    return FixDependencies(
        **{
            ServiceNames.config: default_config,
            ServiceNames.async_engine: db_engine,
            ServiceNames.graph_db_access: graph_database_access_manager,
            ServiceNames.session_maker: async_session_maker,
            ServiceNames.workspace_repo: workspace_repository,
            ServiceNames.certificate_store: cert_store,
            ServiceNames.notification_service: notification_service,
            ServiceNames.domain_event_sender: domain_event_sender,
            ServiceNames.invitation_repository: invitation_repository,
            ServiceNames.user_notification_settings_repository: UserNotificationSettingsRepository(async_session_maker),
            ServiceNames.analytics_event_sender: analytics_event_sender,
            ServiceNames.api_token_service: api_token_service,
            ServiceNames.password_helper: password_helper,
            ServiceNames.jwt_strategy: jwt_strategy,
            ServiceNames.gcp_service_account_repo: gcp_service_account_key_repo,
            ServiceNames.inventory: inventory_service,
            ServiceNames.aws_tier_preference_repo: AwsTierPreferenceRepository(async_session_maker),
            ServiceNames.azure_subscription_repo: azure_subscription_credentials_repo,
            ServiceNames.gcp_service_account_service: gcp_service_account_service,
            ServiceNames.azure_subscription_service: azure_subscription_service,
            ServiceNames.jwt_service: jwt_service,
            ServiceNames.temp_store_redis: redis,
            ServiceNames.user_repo: user_repository,
        }
    )


# noinspection PyUnresolvedReferences
@pytest.fixture
async def fast_api(
    fix_deps: FixDependencies, session: AsyncSession, default_config: Config, async_session_maker: AsyncSessionMaker
) -> FastAPI:
    app: FastAPI = await fast_api_app(default_config, fix_deps)
    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_async_session_maker] = lambda: async_session_maker
    app.dependency_overrides[get_config] = lambda: default_config
    app.dependency_overrides[fix_dependencies] = lambda: fix_deps
    return app


@pytest.fixture
async def api_client(fast_api: FastAPI) -> AsyncIterator[AsyncClient]:  # noqa: F811
    async with AsyncClient(app=fast_api, base_url="http://test") as ac:
        yield ac


stripe_customer_id = StripeCustomerId("dummy_customer_id")
stripe_payment_intent_id = "dummy_payment_intent_id"
stripe_payment_method_id = "dummy_payment_method_id"
stripe_subscription_id = StripeSubscriptionId("dummy_subscription_id")
stripe_refund_id = "dummy_refund_id"


class StripeDummyClient(StripeClient):
    def __init__(self) -> None:
        self.requests: List[Json] = []
        super().__init__("some dummy key")

    async def create_customer(
        self, workspace_id: WorkspaceId, **params: Unpack[stripe.Customer.CreateParams]
    ) -> StripeCustomerId:
        self.requests.append(dict(call="create_customer", **params))
        return stripe_customer_id

    async def create_subscription(
        self, customer_id: StripeCustomerId, payment_method_id: str, billing_period: BillingPeriod
    ) -> StripeSubscriptionId:
        self.requests.append(
            dict(call="create_subscription", customer_id=customer_id, payment_method_id=payment_method_id)
        )
        return stripe_subscription_id

    async def create_usage_record(
        self, subscription_id: str, tier: ProductTier, nr_of_accounts: int, nr_of_seats: int
    ) -> Dict[str, int]:
        return {}

    async def refund(self, payment_intent_id: str) -> stripe.Refund:
        self.requests.append(dict(call="refund", payment_intent_id=payment_intent_id))
        return stripe.Refund(id=stripe_refund_id)

    async def activation_price_id(self) -> str:
        self.requests.append(dict(call="activation_price_id"))
        return "activate_price_id"

    async def get_price_ids_by_product_id(self) -> Dict[str, str]:
        self.requests.append(dict(call="get_price_ids_by_product_id"))
        return {"Enterprise": "p1", "Business": "p2", "Plus": "p3"}

    @alru_cache(ttl=600)
    async def get_prices(self) -> List[stripe.Price]:
        self.requests.append(dict(call="get_prices"))
        return []

    async def checkout_session(self, customer: str, **params: Any) -> str:  # type: ignore # noqa
        self.requests.append(dict(call="checkout_session", customer=customer))
        return f"https://localhost/{customer}/checkout"

    async def billing_portal_session(self, customer: str, **params: Any) -> str:  # type: ignore # noqa
        self.requests.append(dict(call="billing_portal_session", customer=customer))
        return f"https://localhost/{customer}/billing"

    async def payment_method_id_from_intent(
        self, id: str, **params: Unpack[stripe.PaymentIntent.RetrieveParams]
    ) -> str:
        self.requests.append(dict(call="payment_method_id_from_intent", id=id))
        return stripe_payment_method_id

    async def update_customer(self, cid: StripeCustomerId, **params: Unpack[stripe.Customer.ModifyParams]) -> None:
        self.requests.append(dict(call="update_customer", id=id, **params))


@pytest.fixture
def stripe_client() -> StripeDummyClient:
    return StripeDummyClient()


@pytest.fixture
def stripe_service(
    user_repository: UserRepository,
    subscription_repository: SubscriptionRepository,
    workspace_repository: WorkspaceRepository,
    async_session_maker: AsyncSessionMaker,
    domain_event_sender: InMemoryDomainEventPublisher,
    stripe_client: StripeDummyClient,
    billing_entry_service: BillingEntryService,
) -> StripeServiceImpl:
    return StripeServiceImpl(
        stripe_client,
        "dummy_secret",
        "day",
        user_repository,
        subscription_repository,
        workspace_repository,
        async_session_maker,
        domain_event_sender,
        billing_entry_service,
    )


@pytest.fixture
async def billing_job(
    aws_marketplace_handler: AwsMarketplaceHandler,
    stripe_service: StripeServiceImpl,
    subscription_repository: SubscriptionRepository,
    workspace_repository: WorkspaceRepository,
    default_config: Config,
    billing_entry_service: BillingEntryService,
) -> BillingJob:
    return BillingJob(
        aws_marketplace_handler,
        stripe_service,
        subscription_repository,
        workspace_repository,
        billing_entry_service,
        default_config,
    )


@frozen
class NotificationEmail:
    to: str
    subject: str
    text: str
    html: Optional[str]


class InMemoryEmailSender(EmailSender):
    def __init__(self) -> None:
        self.call_args: List[NotificationEmail] = []

    async def send_email(self, *, to: str, subject: str, text: str, html: str | None, **kwargs: Any) -> None:
        self.call_args.append(NotificationEmail(to, subject, text, html))


@pytest.fixture
def email_sender() -> InMemoryEmailSender:
    return InMemoryEmailSender()


class JwtServiceMock(JwtService):
    def __init__(self) -> None:  # noqa
        self.secret = "secret"

    async def encode(self, payload: Json, audience: List[str]) -> str:
        payload["aud"] = audience
        return jwt.encode(payload, self.secret, algorithm="HS256")

    async def decode(self, token: str, audience: List[str]) -> Optional[Json]:
        try:
            data: Json = jwt.decode(token, self.secret, algorithms=["HS256"], audience=audience)
            return data
        except jwt.PyJWTError:
            return None


@pytest.fixture
def jwt_service() -> JwtService:
    return JwtServiceMock()


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
    http_client: AsyncClient,
    domain_event_sender: DomainEventPublisher,
    domain_event_subscriber: DomainEventSubscriber,
    redis_publisher_mock: RedisStreamPublisherMock,
    jwt_service: JwtService,
) -> NotificationService:
    service = NotificationService(
        default_config,
        workspace_repository,
        graph_database_access_manager,
        user_repository,
        inventory_service,
        redis,
        async_session_maker,
        http_client,
        domain_event_sender,
        domain_event_subscriber,
        jwt_service,
    )
    service.alert_publisher = redis_publisher_mock
    service.email_sender = email_sender
    return service


@pytest.fixture
def user_notification_repository(async_session_maker: AsyncSessionMaker) -> UserNotificationSettingsRepository:
    return UserNotificationSettingsRepository(async_session_maker)
