#  Copyright (c) 2024. Some Engineering
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

from typing import List, Optional
import uuid
from fixbackend.base_model import CreatedUpdatedMixin, Base

from sqlalchemy import Boolean, ForeignKey, Text, select

from sqlalchemy.orm import Mapped, mapped_column
from fixbackend.cloud_accounts.models import (
    GcpServiceAccountKey,
)
from fixbackend.errors import ResourceNotFound
from fixbackend.ids import WorkspaceId, GcpServiceAccountKeyId
from fixbackend.sqlalechemy_extensions import GUID
from fixbackend.types import AsyncSessionMaker

from datetime import datetime


class GcpServiceAccountKeyEntity(Base, CreatedUpdatedMixin):
    __tablename__ = "gcp_service_account_key"

    id: Mapped[GcpServiceAccountKeyId] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[WorkspaceId] = mapped_column(
        GUID, ForeignKey("organization.id"), nullable=False, index=True, unique=True
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)
    can_access_sa: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    def to_model(self) -> GcpServiceAccountKey:
        return GcpServiceAccountKey(
            id=self.id,
            tenant_id=self.tenant_id,
            value=self.value,
            can_access_sa=self.can_access_sa,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class GcpServiceAccountKeyRepository:

    def __init__(self, session_maker: AsyncSessionMaker):
        self._session_maker = session_maker

    async def create(
        self,
        tenant_id: WorkspaceId,
        value: str,
    ) -> GcpServiceAccountKey:
        async with self._session_maker() as session:
            entity = GcpServiceAccountKeyEntity(tenant_id=tenant_id, value=value)
            session.add(entity)
            await session.commit()
            await session.refresh(entity)
            return entity.to_model()

    async def get(self, key_id: GcpServiceAccountKeyId) -> Optional[GcpServiceAccountKey]:
        async with self._session_maker() as session:
            query = select(GcpServiceAccountKeyEntity).filter(GcpServiceAccountKeyEntity.id == key_id)
            result = await session.execute(query)
            entity = result.scalars().first()
            if entity is None:
                return None
            return entity.to_model()

    async def list_created_after(self, time: datetime) -> List[GcpServiceAccountKey]:
        async with self._session_maker() as session:
            query = select(GcpServiceAccountKeyEntity).filter(GcpServiceAccountKeyEntity.created_at > time)
            result = await session.execute(query)
            return [entity.to_model() for entity in result.scalars()]

    async def list_created_before(self, time: datetime) -> List[GcpServiceAccountKey]:
        async with self._session_maker() as session:
            query = select(GcpServiceAccountKeyEntity).filter(GcpServiceAccountKeyEntity.created_at < time)
            result = await session.execute(query)
            return [entity.to_model() for entity in result.scalars()]

    async def update_status(self, key_id: GcpServiceAccountKeyId, can_access_sa: bool) -> GcpServiceAccountKey:
        async with self._session_maker() as session:
            query = select(GcpServiceAccountKeyEntity).filter(GcpServiceAccountKeyEntity.id == key_id)
            result = await session.execute(query)
            entity = result.scalars().first()
            if entity is None:
                raise ResourceNotFound(f"Service account json with id {key_id} not found")
            entity.can_access_sa = can_access_sa
            await session.commit()
            await session.refresh(entity)
            return entity.to_model()

    async def delete(self, key_id: GcpServiceAccountKeyId) -> None:
        async with self._session_maker() as session:
            query = select(GcpServiceAccountKeyEntity).filter(GcpServiceAccountKeyEntity.id == key_id)
            result = await session.execute(query)
            entity = result.scalars().first()
            if entity is None:
                return None
            await session.delete(entity)
            await session.commit()
