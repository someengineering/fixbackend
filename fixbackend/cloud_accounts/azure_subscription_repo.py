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
    AzureSubscriptionCredentials,
)
from fixbackend.errors import ResourceNotFound
from fixbackend.ids import AzureSubscriptionCredentialsId, WorkspaceId
from fixbackend.sqlalechemy_extensions import GUID
from fixbackend.types import AsyncSessionMaker

from datetime import datetime
from fixcloudutils.util import utc


class AzureSubscriptionCredentialsEntity(Base, CreatedUpdatedMixin):
    __tablename__ = "azure_subscription_credential"

    id: Mapped[AzureSubscriptionCredentialsId] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[WorkspaceId] = mapped_column(
        GUID, ForeignKey("organization.id"), nullable=False, index=True, unique=True
    )
    azure_tenant_id: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # ID of the service principal's tenant. Also called its "directory" ID.
    client_id: Mapped[str] = mapped_column(Text, nullable=False)  # The service principal's client ID
    client_secret: Mapped[str] = mapped_column(Text, nullable=False)  # One of the service principal's client secrets
    can_access_azure_account: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    def to_model(self) -> AzureSubscriptionCredentials:
        return AzureSubscriptionCredentials(
            id=self.id,
            tenant_id=self.tenant_id,
            azure_tenant_id=self.azure_tenant_id,
            client_id=self.client_id,
            client_secret=self.client_secret,
            can_access_azure_account=self.can_access_azure_account,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class AzureSubscriptionCredentialsRepository:

    def __init__(self, session_maker: AsyncSessionMaker):
        self._session_maker = session_maker

    async def upsert(
        self,
        tenant_id: WorkspaceId,
        azure_tenant_id: str,
        client_id: str,
        client_secret: str,
    ) -> AzureSubscriptionCredentials:
        async with self._session_maker() as session:

            # update existing
            statement = select(AzureSubscriptionCredentialsEntity).filter(
                AzureSubscriptionCredentialsEntity.tenant_id == tenant_id
            )
            result = await session.execute(statement)
            existing = result.scalars().first()
            if existing is not None:
                existing.azure_tenant_id = azure_tenant_id
                existing.client_id = client_id
                existing.client_secret = client_secret
                existing.created_at = utc()  # update to trigger list_created_after
                model = existing.to_model()
                await session.commit()
                return model

            # create new
            entity = AzureSubscriptionCredentialsEntity(
                tenant_id=tenant_id,
                azure_tenant_id=azure_tenant_id,
                client_id=client_id,
                client_secret=client_secret,
            )
            session.add(entity)
            await session.commit()
            await session.refresh(entity)
            return entity.to_model()

    async def get(self, key_id: AzureSubscriptionCredentialsId) -> Optional[AzureSubscriptionCredentials]:
        async with self._session_maker() as session:
            query = select(AzureSubscriptionCredentialsEntity).filter(AzureSubscriptionCredentialsEntity.id == key_id)
            result = await session.execute(query)
            entity = result.scalars().first()
            if entity is None:
                return None
            return entity.to_model()

    async def get_by_tenant(self, tenant_id: WorkspaceId) -> Optional[AzureSubscriptionCredentials]:
        async with self._session_maker() as session:
            query = select(AzureSubscriptionCredentialsEntity).filter(
                AzureSubscriptionCredentialsEntity.tenant_id == tenant_id
            )
            result = await session.execute(query)
            entity = result.scalars().first()
            if entity is None:
                return None

            return entity.to_model()

    async def list_created_after(self, time: datetime, can_access_azure_account: Optional[bool] = None) -> List[AzureSubscriptionCredentials]:
        async with self._session_maker() as session:
            filters = [AzureSubscriptionCredentialsEntity.created_at > time]
            if can_access_azure_account is not None:
                filters.append(AzureSubscriptionCredentialsEntity.can_access_azure_account.is_(can_access_azure_account))
            query = select(AzureSubscriptionCredentialsEntity).filter(*filters)
            result = await session.execute(query)
            return [entity.to_model() for entity in result.scalars()]

    async def list_created_before(self, time: datetime) -> List[AzureSubscriptionCredentials]:
        async with self._session_maker() as session:
            query = select(AzureSubscriptionCredentialsEntity).filter(
                AzureSubscriptionCredentialsEntity.created_at < time
            )
            result = await session.execute(query)
            return [entity.to_model() for entity in result.scalars()]

    async def update_status(
        self, key_id: AzureSubscriptionCredentialsId, can_access_accounts: bool
    ) -> AzureSubscriptionCredentials:
        async with self._session_maker() as session:
            query = select(AzureSubscriptionCredentialsEntity).filter(AzureSubscriptionCredentialsEntity.id == key_id)
            result = await session.execute(query)
            entity = result.scalars().first()
            if entity is None:
                raise ResourceNotFound(f"Service account json with id {key_id} not found")
            entity.can_access_azure_account = can_access_accounts
            await session.commit()
            await session.refresh(entity)
            return entity.to_model()

    async def delete(self, key_id: AzureSubscriptionCredentialsId) -> None:
        async with self._session_maker() as session:
            query = select(AzureSubscriptionCredentialsEntity).filter(AzureSubscriptionCredentialsEntity.id == key_id)
            result = await session.execute(query)
            entity = result.scalars().first()
            if entity is None:
                return None
            await session.delete(entity)
            await session.commit()
