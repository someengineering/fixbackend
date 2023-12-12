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
from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator, Optional, List
from uuid import UUID

from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import select, INT, String, func
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.base_model import Base
from fixbackend.ids import SecurityTier, WorkspaceId, CloudAccountId
from fixbackend.metering import MeteringRecord, MeteringSummary
from fixbackend.sqlalechemy_extensions import UTCDateTime
from fixbackend.types import AsyncSessionMaker


class MeteringRecordEntity(Base):
    __tablename__ = "metering"

    id: Mapped[UUID] = mapped_column(GUID, primary_key=True)
    tenant_id: Mapped[WorkspaceId] = mapped_column(GUID, nullable=False, index=True)
    cloud: Mapped[str] = mapped_column(String(10), nullable=True, default="aws")
    account_id: Mapped[CloudAccountId] = mapped_column(String(36), nullable=True, default="")
    account_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    nr_of_resources_collected: Mapped[int] = mapped_column(INT, nullable=False)
    nr_of_error_messages: Mapped[int] = mapped_column(INT, nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    duration: Mapped[int] = mapped_column(INT, nullable=False)
    security_tier: Mapped[str] = mapped_column(String(64), nullable=False)

    @staticmethod
    def from_model(model: MeteringRecord) -> MeteringRecordEntity:
        return MeteringRecordEntity(
            id=model.id,
            tenant_id=model.workspace_id,
            timestamp=model.timestamp,
            job_id=model.job_id,
            task_id=model.task_id,
            cloud=model.cloud,
            account_id=model.account_id,
            account_name=model.account_name,
            nr_of_resources_collected=model.nr_of_resources_collected,
            nr_of_error_messages=model.nr_of_error_messages,
            started_at=model.started_at,
            duration=model.duration,
            security_tier=model.security_tier.value,
        )

    def to_model(self) -> MeteringRecord:
        return MeteringRecord(
            id=self.id,
            workspace_id=self.tenant_id,
            timestamp=self.timestamp,
            job_id=self.job_id,
            task_id=self.task_id,
            cloud=self.cloud,
            account_id=self.account_id,
            account_name=self.account_name,
            nr_of_resources_collected=self.nr_of_resources_collected,
            nr_of_error_messages=self.nr_of_error_messages,
            started_at=self.started_at,
            duration=self.duration,
            security_tier=SecurityTier(self.security_tier),
        )


class MeteringRepository:
    def __init__(self, session_maker: AsyncSessionMaker) -> None:
        self.session_maker = session_maker

    async def add(self, records: List[MeteringRecord]) -> None:
        if len(records) == 0:
            return
        async with self.session_maker() as session:
            for record in records:
                session.add(MeteringRecordEntity.from_model(record))
            await session.commit()

    async def collect_summary(
        self,
        workspace_id: WorkspaceId,
        *,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        min_resources_collected: int = 0,
        min_nr_of_collects: int = 0,
    ) -> AsyncIterator[MeteringSummary]:
        query = (
            select(
                MeteringRecordEntity.account_id,
                MeteringRecordEntity.account_name,
                func.count().label("num_records"),
                func.group_concat(func.distinct(MeteringRecordEntity.security_tier)).label("security_tiers"),
            )
            .where(
                (MeteringRecordEntity.tenant_id == workspace_id)
                & (MeteringRecordEntity.nr_of_resources_collected >= min_resources_collected)
            )
            .group_by(MeteringRecordEntity.account_id, MeteringRecordEntity.account_name)
        )
        if start is not None:
            query = query.where(MeteringRecordEntity.timestamp >= start)
        if end is not None:
            query = query.where(MeteringRecordEntity.timestamp <= end)
        async with self.session_maker() as session:
            async for (account_id, account_name, count, tiers) in await session.stream(query):
                if count >= min_nr_of_collects:
                    tiers = [SecurityTier(t) for t in tiers.split(",")]

                    max_tier = max(tiers, default=SecurityTier.Free)

                    yield MeteringSummary(
                        account_id=account_id,
                        account_name=account_name,
                        count=count,
                        security_tier=max_tier,
                    )

    async def list(
        self,
        workspace_id: WorkspaceId,
        *,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AsyncIterator[MeteringRecord]:
        async with self.session_maker() as session:
            query = (
                select(MeteringRecordEntity)
                .where(MeteringRecordEntity.tenant_id == workspace_id)
                .limit(limit)
                .offset(offset)
            )
            if start is not None:
                query = query.where(MeteringRecordEntity.timestamp >= start)
            if end is not None:
                query = query.where(MeteringRecordEntity.timestamp <= end)
            async for (record,) in await session.stream(query):
                yield record.to_model()
