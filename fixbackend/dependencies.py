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
from typing import Annotated

from arq import ArqRedis
from fastapi.params import Depends
from fixcloudutils.redis.pub_sub import RedisPubSubPublisher
from fixcloudutils.service import Dependencies
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from fixbackend.collect.collect_queue import RedisCollectQueue
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.inventory.inventory_client import InventoryClient
from fixbackend.inventory.inventory_service import InventoryService
from fixbackend.types import AsyncSessionMaker


class ServiceNames:
    arg_redis = "arq_redis"
    readonly_redis = "readonly_redis"
    readwrite_redis = "readwrite_redis"
    collect_queue = "collect_queue"
    async_engine = "async_engine"
    session_maker = "session_maker"
    cloud_account_repo = "cloud_account_repo"
    next_run_repo = "next_run_repo"
    graph_db_access = "graph_db_access"
    inventory = "inventory"
    inventory_client = "inventory_client"
    dispatching = "dispatching"
    cloudaccount_publisher = "cloudaccount_publisher"


class FixDependencies(Dependencies):
    @property
    def arq_redis(self) -> ArqRedis:
        return self.service(ServiceNames.arg_redis, ArqRedis)

    @property
    def collect_queue(self) -> RedisCollectQueue:
        return self.service(ServiceNames.collect_queue, RedisCollectQueue)

    @property
    def async_engine(self) -> AsyncEngine:
        return self.service(ServiceNames.async_engine, AsyncEngine)

    @property
    def session_maker(self) -> AsyncSessionMaker:
        return self.service(ServiceNames.async_engine, AsyncSessionMaker)  # type: ignore

    @property
    def inventory(self) -> InventoryService:
        return self.service(ServiceNames.inventory, InventoryService)

    @property
    def inventory_client(self) -> InventoryClient:
        return self.service(ServiceNames.inventory, InventoryClient)

    @property
    def readonly_redis(self) -> Redis:
        return self.service(ServiceNames.readonly_redis, Redis)

    @property
    def graph_database_access(self) -> GraphDatabaseAccessManager:
        return self.service(ServiceNames.graph_db_access, GraphDatabaseAccessManager)

    @property
    def cloudaccount_publisher(self) -> RedisPubSubPublisher:
        return self.service(ServiceNames.cloudaccount_publisher, RedisPubSubPublisher)


# placeholder for dependencies, will be replaced during the app initialization
def fix_dependencies() -> FixDependencies:
    raise RuntimeError("Dependencies dependency not initialized yet.")


FixDependency = Annotated[FixDependencies, Depends(fix_dependencies)]
