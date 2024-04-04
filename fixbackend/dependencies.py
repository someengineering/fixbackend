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
from typing import Annotated, cast

from arq import ArqRedis
from fastapi.params import Depends
from fixcloudutils.service import Dependencies
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from fixbackend.certificates.cert_store import CertificateStore
from fixbackend.config import Config
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.jwt import JwtService, JwtServiceImpl
from fixbackend.types import AsyncSessionMaker


class ServiceNames:
    config = "config"
    http_client = "http_client"
    arq_redis = "arq_redis"
    readonly_redis = "readonly_redis"
    readwrite_redis = "readwrite_redis"
    temp_store_redis = "temp_store_redis"
    collect_queue = "collect_queue"
    async_engine = "async_engine"
    session_maker = "session_maker"
    cloud_account_repo = "cloud_account_repo"
    next_run_repo = "next_run_repo"
    metering_repo = "metering_repo"
    graph_db_access = "graph_db_access"
    inventory = "inventory"
    inventory_client = "inventory_client"
    dispatching = "dispatching"
    certificate_store = "certificate_store"
    domain_event_redis_stream_publisher = "domain_event_redis_stream_publisher"
    domain_event_sender = "domain_event_sender"
    customerio_consumer = "customerio_consumer"
    aws_marketplace_handler = "aws_marketplace_handler"
    workspace_repo = "workspace_repo"
    user_repo = "user_repo"
    subscription_repo = "subscription_repo"
    billing = "billing"
    cloud_account_service = "cloud_account_service"
    domain_event_subscriber = "domain_event_subscriber"
    invitation_repository = "invitation_repository"
    analytics_event_sender = "analytics_event_sender"
    notification_service = "notification_service"
    user_notification_settings_repository = "user_notification_settings_repository"
    email_on_signup_consumer = "email_on_signup_consumer"
    billing_entry_service = "billing_entry_services"
    role_repository = "role_repository"
    jwt_service = "jwt_service"
    scheduled_email_sender = "scheduled_email_sender"
    trial_end_service = "trial_end_service"


class FixDependencies(Dependencies):
    @property
    def config(self) -> Config:
        return self.service(ServiceNames.config, Config)

    @property
    def http_client(self) -> AsyncClient:
        return self.service(ServiceNames.http_client, AsyncClient)

    @property
    def arq_redis(self) -> ArqRedis:
        return self.service(ServiceNames.arq_redis, ArqRedis)

    @property
    def async_engine(self) -> AsyncEngine:
        return self.service(ServiceNames.async_engine, AsyncEngine)

    @property
    def session_maker(self) -> AsyncSessionMaker:
        return cast(AsyncSessionMaker, self.lookup[ServiceNames.session_maker])

    @property
    def readonly_redis(self) -> Redis:
        return self.service(ServiceNames.readonly_redis, Redis)

    @property
    def readwrite_redis(self) -> Redis:
        return self.service(ServiceNames.readwrite_redis, Redis)

    @property
    def graph_database_access(self) -> GraphDatabaseAccessManager:
        return self.service(ServiceNames.graph_db_access, GraphDatabaseAccessManager)

    @property
    def certificate_store(self) -> CertificateStore:
        return self.service(ServiceNames.certificate_store, CertificateStore)

    @property
    def domain_event_sender(self) -> DomainEventPublisher:
        return self.service(ServiceNames.domain_event_sender, DomainEventPublisher)  # type: ignore

    @property
    def jwt_service(self) -> JwtService:
        return self.service(ServiceNames.jwt_service, JwtServiceImpl)

    async def stop(self) -> None:
        await super().stop()
        # non-service objects that need to be stopped explicitly
        if engine := self.service(ServiceNames.async_engine, AsyncEngine):
            await engine.dispose()


# placeholder for dependencies, will be replaced during the app initialization
def fix_dependencies() -> FixDependencies:
    raise RuntimeError("Dependencies dependency not initialized yet.")


FixDependency = Annotated[FixDependencies, Depends(fix_dependencies)]
