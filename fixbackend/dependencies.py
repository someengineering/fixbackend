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
from fixcloudutils.service import Dependencies
from sqlalchemy.ext.asyncio import AsyncEngine

from fixbackend.collect.collect_queue import RedisCollectQueue


class ServiceNames:
    arg_redis = "arq_redis"
    collect_queue = "collect_queue"
    async_engine = "async_engine"


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


# placeholder for dependencies, will be replaced during the app initialization
def fix_dependencies() -> FixDependencies:
    raise RuntimeError("Dependencies dependency not initialized yet.")


FixDependency = Annotated[FixDependencies, Depends(fix_dependencies)]
