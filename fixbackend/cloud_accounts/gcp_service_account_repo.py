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

from typing import Optional
import uuid
from fixbackend.base_model import CreatedUpdatedMixin, Base

from sqlalchemy import Boolean, ForeignKey, Text, select

from sqlalchemy.orm import Mapped, mapped_column
from fixbackend.cloud_accounts.models import (
    GcpServiceAccountJson,
)
from fixbackend.errors import ResourceNotFound
from fixbackend.ids import WorkspaceId, GcpServiceAccountJsonId
from fixbackend.sqlalechemy_extensions import GUID
from fixbackend.types import AsyncSessionMaker


class ServiceAccountJsonEntity(Base, CreatedUpdatedMixin):
    __tablename__ = "gcp_service_account_json"

    id: Mapped[GcpServiceAccountJsonId] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[WorkspaceId] = mapped_column(
        GUID, ForeignKey("organization.id"), nullable=False, index=True, unique=True
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)
    can_access_sa: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    def to_model(self) -> GcpServiceAccountJson:
        return GcpServiceAccountJson(
            id=self.id,
            tenant_id=self.tenant_id,
            value=self.value,
            can_access_sa=self.can_access_sa,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class GcpServiceAccountJsonRepository:

    def __init__(self, session_maker: AsyncSessionMaker):
        self._session_maker = session_maker

    async def create(
        self,
        tenant_id: WorkspaceId,
        value: str,
    ) -> GcpServiceAccountJson:
        async with self._session_maker() as session:
            entity = ServiceAccountJsonEntity(tenant_id=tenant_id, value=value)
            session.add(entity)
            await session.commit()
            await session.refresh(entity)
            return entity.to_model()

    async def get(self, id: GcpServiceAccountJsonId) -> Optional[GcpServiceAccountJson]:
        async with self._session_maker() as session:
            query = select(ServiceAccountJsonEntity).filter(ServiceAccountJsonEntity.id == id)
            result = await session.execute(query)
            entity = result.scalars().first()
            if entity is None:
                return None
            return entity.to_model()

    async def update_status(self, id: GcpServiceAccountJsonId, can_access_sa: bool) -> GcpServiceAccountJson:
        async with self._session_maker() as session:
            query = select(ServiceAccountJsonEntity).filter(ServiceAccountJsonEntity.id == id)
            result = await session.execute(query)
            entity = result.scalars().first()
            if entity is None:
                raise ResourceNotFound(f"Service account json with id {id} not found")
            entity.can_access_sa = can_access_sa
            await session.commit()
            await session.refresh(entity)
            return entity.to_model()

    async def delete(self, id: GcpServiceAccountJsonId) -> None:
        async with self._session_maker() as session:
            query = select(ServiceAccountJsonEntity).filter(ServiceAccountJsonEntity.id == id)
            result = await session.execute(query)
            entity = result.scalars().first()
            if entity is None:
                return None
            await session.delete(entity)
            await session.commit()
