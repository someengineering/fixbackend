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
from typing import Annotated, Optional, Sequence, List, Tuple
from pathlib import Path
from fastapi import Depends
from pydantic_settings import BaseSettings
from functools import lru_cache


class Config(BaseSettings):
    environment: str
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
    customerio_baseurl: str
    customerio_site_id: Optional[str]
    customerio_api_key: Optional[str]
    cloud_account_service_event_parallelism: int
    aws_cf_stack_notification_sqs_url: Optional[str]
    oauth_state_token_ttl: int
    profiling_enabled: bool
    profiling_interval: float
    google_analytics_measurement_id: Optional[str]
    google_analytics_api_secret: Optional[str]

    def frontend_cdn_origin(self) -> str:
        return f"{self.cdn_endpoint}/{self.cdn_bucket}/{self.fixui_sha}"

    @property
    def database_url(self) -> str:
        password = f":{self.database_password}" if self.database_password else ""
        return f"mysql+aiomysql://{self.database_user}{password}@{self.database_host}:{self.database_port}/{self.database_name}"  # noqa

    class Config:
        extra = "ignore"  # allow extra fields in the config


def parse_args(argv: Optional[Sequence[str]] = None) -> Namespace:
    parser = ArgumentParser(prog="FIX Backend")
    parser.add_argument("--debug", action="store_true", default=False)
    parser.add_argument("--instance-id", default=os.environ.get("FIX_INSTANCE_ID", "single"))
    parser.add_argument("--environment", default=os.environ.get("FIX_ENVIRONMENT", "dev"))
    parser.add_argument("--database-name", default=os.environ.get("FIX_DATABASE_NAME", "fix"))
    parser.add_argument("--database-user", default=os.environ.get("FIX_DATABASE_USER", "fix"))
    parser.add_argument("--database-password", default=os.environ.get("FIX_DATABASE_PASSWORD", "fix"))
    parser.add_argument("--database-host", default=os.environ.get("FIX_DATABASE_HOST", "localhost"))
    parser.add_argument("--database-port", type=int, default=int(os.environ.get("FIX_DATABASE_PORT", "3306")))
    parser.add_argument("--secret", default=os.environ.get("FIX_OAUTH_SECRET", "secret"))
    parser.add_argument("--google-oauth-client-id", default=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""))
    parser.add_argument("--google-oauth-client-secret", default=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""))
    parser.add_argument("--github-oauth-client-id", default=os.environ.get("GITHUB_OAUTH_CLIENT_ID", ""))
    parser.add_argument("--github-oauth-client-secret", default=os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", ""))
    parser.add_argument(
        "--redis-readwrite-url", default=os.environ.get("REDIS_READWRITE_URL", "redis://localhost:6379/0")
    )
    parser.add_argument(
        "--redis-readonly-url", default=os.environ.get("REDIS_READONLY_URL", "redis://localhost:6379/0")
    )
    parser.add_argument(
        "--redis-temp-store-url", default=os.environ.get("REDIS_TEMP_STORE_URL", "redis://localhost:6379/1")
    )
    parser.add_argument("--redis-queue-url", default=os.environ.get("REDIS_QUEUE_URL", "redis://localhost:6379/5"))
    parser.add_argument("--redis-password", default=os.environ.get("REDIS_PASSWORD"))
    parser.add_argument("--skip-migrations", default=False, action="store_true")
    parser.add_argument("--cdn-endpoint", default=os.environ.get("FIXUI_CDN_ENDPOINT", "https://cdn.some.engineering"))
    parser.add_argument("--cdn-bucket", default=os.environ.get("FIXUI_CDN_BUCKET", "fix-ui"))
    parser.add_argument("--fixui-sha", default=os.environ.get("FIXUI_SHA", "edge"))
    parser.add_argument("--static-assets", type=Path, default=os.environ.get("STATIC_ASSETS"))
    one_week = 3600 * 24 * 7
    parser.add_argument("--session-ttl", type=int, default=int(os.environ.get("SESSION_TTL", one_week)))
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
        "--customerio-baseurl", default=os.environ.get("CUSTOMERIO_BASEURL", "https://track.customer.io")
    )
    parser.add_argument("--customerio-site-id", default=os.environ.get("CUSTOMERIO_SITE_ID"))
    parser.add_argument("--customerio-api-key", default=os.environ.get("CUSTOMERIO_API_KEY"))
    parser.add_argument("--mode", choices=["app", "dispatcher", "billing"], default=os.environ.get("MODE", "app"))
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
    parser.add_argument("--google-analytics-api-secret", default=os.environ.get("GOOGLE_ANALYTICS_API_SECRET"))
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
