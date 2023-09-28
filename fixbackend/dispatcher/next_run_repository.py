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
from typing import AsyncIterator

from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import DATETIME, select
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.base_model import Base
from fixbackend.ids import CloudAccountId
from fixbackend.types import AsyncSessionMaker


class NextRun(Base):
    __tablename__ = "next_run"

    cloud_account_id: Mapped[CloudAccountId] = mapped_column(GUID, primary_key=True)
    at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, index=True)


class NextRunRepository:
    def __init__(self, session_maker: AsyncSessionMaker) -> None:
        self.session_maker = session_maker

    async def create(self, cid: CloudAccountId, next_run: datetime) -> None:
        async with self.session_maker() as session:
            session.add(NextRun(cloud_account_id=cid, at=next_run))
            await session.commit()

    async def update_next_run_at(self, cid: CloudAccountId, next_run: datetime) -> None:
        async with self.session_maker() as session:
            if nxt := await session.get(NextRun, cid):
                nxt.at = next_run
                await session.commit()

    async def delete(self, cid: CloudAccountId) -> None:
        async with self.session_maker() as session:
            results = await session.execute(select(NextRun).where(NextRun.cloud_account_id == cid))
            if run := results.unique().scalar():
                await session.delete(run)
                await session.commit()

    async def older_than(self, at: datetime) -> AsyncIterator[CloudAccountId]:
        async with self.session_maker() as session:
            async for (entry,) in await session.stream(select(NextRun).where(NextRun.at < at)):
                yield entry.cloud_account_id
