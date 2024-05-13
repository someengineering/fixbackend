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
from datetime import datetime
from typing import AsyncIterator, Tuple, Optional

from fastapi_users_db_sqlalchemy.generics import GUID
from fixcloudutils.util import utc
from sqlalchemy import select
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.base_model import Base
from fixbackend.config import ProductTierSettings
from fixbackend.ids import WorkspaceId, ProductTier
from fixbackend.sqlalechemy_extensions import UTCDateTime
from fixbackend.types import AsyncSessionMaker


class NextTenantRun(Base):
    __tablename__ = "next_tenant_run"

    tenant_id: Mapped[WorkspaceId] = mapped_column(GUID, primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)


class NextRunRepository:
    def __init__(self, session_maker: AsyncSessionMaker) -> None:
        self.session_maker = session_maker

    async def create(self, workspace_id: WorkspaceId, next_run: datetime) -> None:
        async with self.session_maker() as session:
            next_tenant_run = NextTenantRun(tenant_id=workspace_id, at=next_run)
            session.add(next_tenant_run)
            await session.commit()

    async def get(self, workspace_id: WorkspaceId) -> Optional[datetime]:
        async with self.session_maker() as session:
            results = await session.execute(select(NextTenantRun).where(NextTenantRun.tenant_id == workspace_id))
            if run := results.unique().scalar():
                return run.at
            else:
                return None

    def next_run_for(self, product_tier: ProductTier, last_run: Optional[datetime] = None) -> datetime:
        now = utc()
        settings = ProductTierSettings[product_tier]
        delta = settings.scan_interval
        initial_time = last_run or now
        diff = now - initial_time
        if diff.total_seconds() > 0:  # if the last run is in the past, make sure the next run is in the future
            periods = (diff // delta) + 1
            result = initial_time + (delta * periods)
        else:  # next run is already in the future. compute offset.
            result = initial_time + delta
        return result

    async def update_next_run_for(
        self, tenant: WorkspaceId, product_tier: ProductTier, last_run: Optional[datetime] = None
    ) -> datetime:
        result = self.next_run_for(product_tier, last_run)
        await self.update_next_run_at(tenant, result)
        return result

    async def update_next_run_at(self, workspace_id: WorkspaceId, next_run: datetime) -> None:
        async with self.session_maker() as session:
            if nxt := await session.get(NextTenantRun, workspace_id):
                nxt.at = next_run
                await session.commit()

    async def delete(self, workspace_id: WorkspaceId) -> None:
        async with self.session_maker() as session:
            results = await session.execute(select(NextTenantRun).where(NextTenantRun.tenant_id == workspace_id))
            if run := results.unique().scalar():
                await session.delete(run)
                await session.commit()

    async def older_than(self, at: datetime) -> AsyncIterator[Tuple[WorkspaceId, datetime]]:
        async with self.session_maker() as session:
            async for (entry,) in await session.stream(select(NextTenantRun).where(NextTenantRun.at < at)):
                yield entry.tenant_id, entry.at
