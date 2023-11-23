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
from datetime import datetime, timezone
from typing import Optional, Any

import sqlalchemy as sa
from fixcloudutils.asyncio.timed import perf_now
from prometheus_client import Histogram, Gauge
from sqlalchemy import Connection, event
from sqlalchemy.ext.asyncio import AsyncEngine


class UTCDateTime(sa.types.TypeDecorator[sa.types.DateTime]):
    """
    Use this type to store datetime objects.
    It will make sure to use UTC timezone always.
    """

    impl = sa.types.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Optional[Any], dialect: sa.Dialect) -> Optional[Any]:
        if isinstance(value, datetime) and value.tzinfo is not timezone.utc:
            raise ValueError("Only datetime with timezone UTC are supported!")

        return value

    def process_result_value(self, value: Optional[Any], dialect: sa.Dialect) -> Optional[Any]:
        return value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) else value


class EngineMetrics:
    query_start_time = "query_start_time"
    DbStatementDuration = Histogram("db_statement_duration", "Time to execute DB Statements")
    DbConnections = Gauge("db_connections", "Number of active DB connections")

    @classmethod
    def before_execute(cls, connection: Connection, clause: Any, multiparams: Any, params: Any) -> None:  # noqa
        connection.info.setdefault(cls.query_start_time, []).append(perf_now())

    @classmethod
    def after_execute(
        cls, connection: Connection, clause: Any, multiparams: Any, params: Any, result: Any  # noqa
    ) -> None:
        start_time = connection.info[cls.query_start_time].pop()
        cls.DbStatementDuration.observe(perf_now() - start_time)

    @classmethod
    def checkout(cls, connection: Connection, con_read: Any, con_proxy: Any) -> None:  # noqa
        cls.DbConnections.inc()

    @classmethod
    def checkin(cls, connection: Connection, con_read: Any) -> None:  # noqa
        cls.DbConnections.dec()

    @classmethod
    def register(cls, engine: AsyncEngine) -> AsyncEngine:
        event.listen(engine.sync_engine, "before_execute", cls.before_execute)
        event.listen(engine.sync_engine, "after_execute", cls.after_execute)
        event.listen(engine.sync_engine, "checkout", cls.checkout)
        event.listen(engine.sync_engine, "checkin", cls.checkin)
        return engine
