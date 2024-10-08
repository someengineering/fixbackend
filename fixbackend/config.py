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
import os
import sys
from argparse import ArgumentParser, Namespace
from collections import defaultdict
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Optional, Sequence, List, Tuple

import cattrs
from attr import frozen
from fastapi import Depends
from fixcloudutils.types import Json
from pydantic_settings import BaseSettings

from fixbackend.ids import ProductTier, BillingPeriod


class Config(BaseSettings):
    environment: Literal["dev", "prd"]
    instance_id: str
    database_name: str
    database_user: str
    database_password: Optional[str]
    database_host: str
    database_port: int
    secret: str
    google_oauth_client_id: str
    google_oauth_client_secret: str
    github_oauth_client_id: str
    github_oauth_client_secret: str
    redis_readwrite_url: str
    redis_readonly_url: str
    redis_queue_url: str
    redis_temp_store_url: str
    cdn_endpoint: str
    cdn_bucket: str
    fixui_sha: str
    static_assets: Optional[Path]
    session_ttl: int
    available_db_server: List[str]
    inventory_url: str
    cf_template_url: str
    args: Namespace
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_region: str
    ca_cert: Optional[Path]
    host_cert: Optional[Path]
    host_key: Optional[Path]
    signing_cert_1: Optional[Path]
    signing_key_1: Optional[Path]
    signing_cert_2: Optional[Path]
    signing_key_2: Optional[Path]
    cloud_account_service_event_parallelism: int
    aws_cf_stack_notification_sqs_url: Optional[str]
    oauth_state_token_ttl: int
    profiling_enabled: bool
    profiling_interval: float
    google_analytics_measurement_id: Optional[str]
    google_analytics_api_secret: Optional[str]
    posthog_api_key: Optional[str]
    aws_marketplace_url: str
    billing_period: BillingPeriod
    discord_oauth_client_id: str
    discord_oauth_client_secret: str
    slack_oauth_client_id: str
    slack_oauth_client_secret: str
    service_base_url: str
    support_base_url: str
    push_gateway_url: Optional[str]
    stripe_api_key: Optional[str]
    stripe_webhook_key: Optional[str]
    customer_support_users: List[str]
    free_tier_cleanup_timeout_days: int
    azure_tenant_id: str
    azure_client_id: str
    azure_client_secret: str
    account_failed_resource_count: int
    degraded_accounts_ping_interval_hours: int
    auth_rate_limit_per_minute: int

    def frontend_cdn_origin(self) -> str:
        return f"{self.cdn_endpoint}/{self.cdn_bucket}/{self.fixui_sha}"

    @property
    def database_url(self) -> str:
        password = f":{self.database_password}" if self.database_password else ""
        return f"postgresql+asyncpg://{self.database_user}{password}@{self.database_host}:{self.database_port}/{self.database_name}"  # noqa

    class Config:
        extra = "ignore"  # allow extra fields in the config


def parse_args(argv: Optional[Sequence[str]] = None) -> Namespace:
    parser = ArgumentParser(prog="Fix Backend")
    parser.add_argument("--debug", action="store_true", default=False)
    parser.add_argument("--instance-id", default=os.environ.get("FIX_INSTANCE_ID", "single"))
    parser.add_argument("--environment", choices=["dev", "prd"], default=os.environ.get("FIX_ENVIRONMENT", "dev"))
    parser.add_argument("--database-name", default=os.environ.get("FIX_DATABASE_NAME", "fix"))
    parser.add_argument("--database-user", default=os.environ.get("FIX_DATABASE_USER", "fix"))
    parser.add_argument("--database-password", default=os.environ.get("FIX_DATABASE_PASSWORD", "fix"))
    parser.add_argument("--database-host", default=os.environ.get("FIX_DATABASE_HOST", "localhost"))
    parser.add_argument("--database-port", type=int, default=int(os.environ.get("FIX_DATABASE_PORT", "5432")))
    parser.add_argument("--secret", default=os.environ.get("FIX_OAUTH_SECRET", "secret"))
    parser.add_argument("--google-oauth-client-id", default=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""))
    parser.add_argument("--google-oauth-client-secret", default=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""))
    parser.add_argument("--github-oauth-client-id", default=os.environ.get("GITHUB_OAUTH_CLIENT_ID", ""))
    parser.add_argument("--github-oauth-client-secret", default=os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", ""))
    parser.add_argument("--discord-oauth-client-id", default=os.environ.get("DISCORD_OAUTH_CLIENT_ID", ""))
    parser.add_argument("--discord-oauth-client-secret", default=os.environ.get("DISCORD_OAUTH_CLIENT_SECRET", ""))
    parser.add_argument("--slack-oauth-client-id", default=os.environ.get("SLACK_OAUTH_CLIENT_ID", ""))
    parser.add_argument("--slack-oauth-client-secret", default=os.environ.get("SLACK_OAUTH_CLIENT_SECRET", ""))
    parser.add_argument(
        "--redis-readwrite-url", default=os.environ.get("REDIS_READWRITE_URL", "redis://localhost:6379/0")
    )
    parser.add_argument(
        "--redis-readonly-url", default=os.environ.get("REDIS_READONLY_URL", "redis://localhost:6379/0")
    )
    parser.add_argument(
        "--redis-temp-store-url", default=os.environ.get("REDIS_TEMP_STORE_URL", "redis://localhost:6379/5")
    )
    parser.add_argument("--redis-queue-url", default=os.environ.get("REDIS_QUEUE_URL", "redis://localhost:6379/5"))
    parser.add_argument("--redis-password", default=os.environ.get("REDIS_PASSWORD"))
    parser.add_argument("--skip-migrations", default=False, action="store_true")
    parser.add_argument("--cdn-endpoint", default=os.environ.get("FIXUI_CDN_ENDPOINT", "https://cdn.fix.security"))
    parser.add_argument("--cdn-bucket", default=os.environ.get("FIXUI_CDN_BUCKET", "fix-ui"))
    parser.add_argument("--fixui-sha", default=os.environ.get("FIXUI_SHA", "edge"))
    parser.add_argument("--static-assets", type=Path, default=os.environ.get("STATIC_ASSETS"))
    two_days = 3600 * 24 * 2
    parser.add_argument("--session-ttl", type=int, default=int(os.environ.get("SESSION_TTL", two_days)))
    parser.add_argument(
        "--available-db-server", nargs="+", default=os.environ.get("AVAILABLE_DB_SERVER", "").split(",")
    )
    parser.add_argument("--inventory-url", default=os.environ.get("INVENTORY_URL", "http://localhost:8980"))
    parser.add_argument(
        "--cf-template-url",
        default=os.environ.get("CF_TEMPLATE_URL", "https://fixpublic.s3.amazonaws.com/aws/fix-role-dev-eu.yaml"),
    )
    parser.add_argument(
        "--dispatcher", action="store_true", default=False, help="Run the dispatcher instead of the web server"
    )
    parser.add_argument("--aws-access-key-id", default=os.environ.get("AWS_ACCESS_KEY_ID", ""))
    parser.add_argument("--aws-secret-access-key", default=os.environ.get("AWS_SECRET_ACCESS_KEY", ""))
    parser.add_argument("--aws-region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument(
        "--aws-marketplace-metering-sqs-url", default=os.environ.get("AWS_MARKETPLACE_METERING_SQS_URL")
    )
    parser.add_argument(
        "--aws-cf-stack-notification-sqs-url", default=os.environ.get("AWS_CF_STACK_NOTIFICATION_SQS_URL")
    )
    parser.add_argument("--ca-cert", type=Path, default=os.environ.get("CA_CERT"))
    parser.add_argument("--host-cert", type=Path, default=os.environ.get("HOST_CERT"))
    parser.add_argument("--host-key", type=Path, default=os.environ.get("HOST_KEY"))
    parser.add_argument("--signing-cert-1", type=Path, default=os.environ.get("SIGNING_CERT_1"))
    parser.add_argument("--signing-key-1", type=Path, default=os.environ.get("SIGNING_KEY_1"))
    parser.add_argument("--signing-cert-2", type=Path, default=os.environ.get("SIGNING_CERT_2"))
    parser.add_argument("--signing-key-2", type=Path, default=os.environ.get("SIGNING_KEY_2"))
    parser.add_argument(
        "--mode", choices=["app", "dispatcher", "billing", "support"], default=os.environ.get("MODE", "app")
    )
    parser.add_argument(
        "--cloud-account-service-event-parallelism",
        type=int,
        default=int(os.environ.get("CLOUD_ACCOUNT_SERVICE_EVENT_PARALLELISM", "100")),
    )
    parser.add_argument(
        "--oauth-state-token-ttl", type=int, default=int(os.environ.get("OAUTH_STATE_TOKEN_TTL", "3600"))
    )
    parser.add_argument("--profiling-enabled", action="store_true", default=os.environ.get("PROFILING_ENABLED", False))
    parser.add_argument("--profiling-interval", type=float, default=os.environ.get("PROFILING_INTERVAL", 0.001))
    parser.add_argument("--google-analytics-measurement-id", default=os.environ.get("GOOGLE_ANALYTICS_MEASUREMENT_ID"))
    parser.add_argument("--posthog-api-key", default=os.environ.get("POSTHOG_API_KEY"))
    parser.add_argument("--google-analytics-api-secret", default=os.environ.get("GOOGLE_ANALYTICS_API_SECRET"))
    parser.add_argument("--aws-marketplace-url", default=os.environ.get("AWS_MARKETPLACE_URL", ""))
    parser.add_argument("--service-base-url", default=os.environ.get("SERVICE_BASE_URL", ""))
    parser.add_argument("--support-base-url", default=os.environ.get("SUPPORT_BASE_URL", ""))
    parser.add_argument(
        "--billing-period",
        choices=["month", "day"],
        default=os.environ.get("BILLING_PERIOD", "month"),
    )
    parser.add_argument("--push-gateway-url", default=os.environ.get("PUSH_GATEWAY_URL"))
    parser.add_argument("--port", type=int, default=os.environ.get("PORT", 8000))
    parser.add_argument("--stripe-api-key", default=os.environ.get("STRIPE_API_KEY"))
    parser.add_argument("--stripe-webhook-key", default=os.environ.get("STRIPE_WEBHOOK_KEY"))
    parser.add_argument(
        "--customer-support-users", nargs="+", default=os.environ.get("CUSTOMER_SUPPORT_USERS", "").split(",")
    )
    parser.add_argument(
        "--free-tier-cleanup-timeout-days",
        type=int,
        default=int(os.environ.get("FREE_TIER_CLEANUP_TIMEOUT_DAYS", "7")),
    )
    parser.add_argument("--azure-tenant_id", default=os.environ.get("AZURE_APP_TENANT_ID", ""))
    parser.add_argument("--azure-client-id", default=os.environ.get("AZURE_APP_CLIENT_ID", ""))
    parser.add_argument("--azure-client-secret", default=os.environ.get("AZURE_APP_CLIENT_SECRET", ""))
    parser.add_argument("--account-failed-resource-count", default=1)
    parser.add_argument("--degraded-accounts-ping-interval-hours", default=24)
    parser.add_argument("--auth-rate-limit-per-minute", default=4)
    return parser.parse_known_args(argv if argv is not None else sys.argv[1:])[0]


@lru_cache()
def get_config(argv: Optional[Tuple[str, ...]] = None) -> Config:
    args = parse_args(argv)
    args_dict = vars(args)
    args_dict["args"] = args
    return Config(**args_dict)


# placeholder for dependencies, will be replaced during the app initialization
def config() -> Config:
    raise RuntimeError("Config dependency not initialized yet.")


ConfigDependency = Annotated[Config, Depends(config)]


def trial_period_duration() -> timedelta:
    return timedelta(days=14)


@frozen
class ProductTierSetting:
    retention_period: timedelta
    seats_included: int
    seats_max: Optional[int]
    scan_interval: timedelta
    account_limit: Optional[int]
    accounts_included: int
    price_per_account_cents: int

    def to_json(self) -> Json:
        return cattrs.unstructure(self)  # type: ignore


Free = ProductTierSetting(
    retention_period=timedelta(days=31),
    seats_included=1,
    seats_max=1,
    scan_interval=timedelta(days=30),
    account_limit=1,
    accounts_included=0,
    price_per_account_cents=0,
)
Trial = ProductTierSetting(
    retention_period=timedelta(days=183),
    seats_included=1,
    seats_max=None,
    scan_interval=timedelta(hours=1),
    account_limit=None,
    accounts_included=0,
    price_per_account_cents=0,
)
ProductTierSettings = defaultdict(
    lambda: Free,
    {
        ProductTier.Free: Free,
        ProductTier.Trial: Trial,
        ProductTier.Plus: ProductTierSetting(
            retention_period=timedelta(days=92),
            seats_included=2,
            seats_max=20,
            scan_interval=timedelta(days=1),
            account_limit=None,
            accounts_included=3,
            price_per_account_cents=3000,
        ),
        ProductTier.Business: ProductTierSetting(
            retention_period=timedelta(days=183),
            seats_included=5,
            seats_max=50,
            scan_interval=timedelta(hours=1),
            account_limit=None,
            accounts_included=10,
            price_per_account_cents=4000,
        ),
        ProductTier.Enterprise: ProductTierSetting(
            retention_period=timedelta(days=549),
            seats_included=20,
            seats_max=None,
            scan_interval=timedelta(hours=1),
            account_limit=None,
            accounts_included=25,
            price_per_account_cents=5000,
        ),
    },
)
