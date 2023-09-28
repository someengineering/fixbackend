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
from typing import Annotated, List, Optional

from fastapi import Depends
from sqlalchemy import select

from fixbackend.cloud_accounts.models import orm, CloudAccount, AwsCloudAccess
from fixbackend.db import AsyncSessionMaker
from fixbackend.ids import CloudAccountId, TenantId
from abc import ABC, abstractmethod


class CloudAccountRepository(ABC):
    @abstractmethod
    async def create(self, cloud_account: CloudAccount) -> CloudAccount:
        raise NotImplementedError

    @abstractmethod
    async def get(self, id: CloudAccountId) -> Optional[CloudAccount]:
        raise NotImplementedError

    @abstractmethod
    async def list_by_tenant_id(self, tenant_id: TenantId) -> List[CloudAccount]:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, id: CloudAccountId) -> None:
        raise NotImplementedError


class CloudAccountRepositoryImpl(CloudAccountRepository):
    def __init__(
        self,
        session_maker: AsyncSessionMaker,
    ) -> None:
        self.session_maker = session_maker

    async def create(self, cloud_account: CloudAccount) -> CloudAccount:
        """Create a cloud account."""
        async with self.session_maker() as session:
            if isinstance(cloud_account.access, AwsCloudAccess):
                orm_cloud_account = orm.CloudAccount(
                    id=cloud_account.id,
                    tenant_id=cloud_account.tenant_id,
                    cloud="aws",
                    account_id=cloud_account.access.account_id,
                    aws_role_name=cloud_account.access.role_name,
                    aws_external_id=cloud_account.access.external_id,
                )
            else:
                raise ValueError(f"Unknown cloud {cloud_account.access}")
            session.add(orm_cloud_account)
            await session.commit()
            await session.refresh(orm_cloud_account)
            return orm_cloud_account.to_domain()

    async def get(self, id: CloudAccountId) -> Optional[CloudAccount]:
        """Get a single cloud account by id."""
        async with self.session_maker() as session:
            cloud_account = await session.get(orm.CloudAccount, id)
            return cloud_account.to_domain() if cloud_account else None

    async def list_by_tenant_id(self, tenant_id: TenantId) -> List[CloudAccount]:
        """Get a list of cloud accounts by tenant id."""
        async with self.session_maker() as session:
            statement = select(orm.CloudAccount).where(orm.CloudAccount.tenant_id == tenant_id)
            results = await session.execute(statement)
            accounts = results.scalars().all()
            return [acc.to_domain() for acc in accounts]

    async def delete(self, id: CloudAccountId) -> None:
        """Delete a cloud account."""
        async with self.session_maker() as session:
            statement = select(orm.CloudAccount).where(orm.CloudAccount.id == id)
            results = await session.execute(statement)
            cloud_account = results.unique().scalar_one()
            await session.delete(cloud_account)
            await session.commit()


def get_cloud_account_repository(session_maker: AsyncSessionMaker) -> CloudAccountRepository:
    return CloudAccountRepositoryImpl(session_maker)


CloudAccountRepositoryDependency = Annotated[CloudAccountRepository, Depends(get_cloud_account_repository)]
