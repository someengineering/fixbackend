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
from abc import ABC, abstractmethod
from typing import Annotated, Callable, List, Optional

from fastapi import Depends
from sqlalchemy import select

from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount, orm
from fixbackend.db import AsyncSessionMakerDependency
from fixbackend.errors import ResourceNotFound
from fixbackend.ids import FixCloudAccountId, WorkspaceId
from fixbackend.types import AsyncSessionMaker


class CloudAccountRepository(ABC):
    @abstractmethod
    async def create(self, cloud_account: CloudAccount) -> CloudAccount:
        raise NotImplementedError

    @abstractmethod
    async def get(self, id: FixCloudAccountId) -> Optional[CloudAccount]:
        raise NotImplementedError

    @abstractmethod
    async def update(self, id: FixCloudAccountId, update_fn: Callable[[CloudAccount], CloudAccount]) -> CloudAccount:
        raise NotImplementedError

    @abstractmethod
    async def list_by_workspace_id(
        self, workspace_id: WorkspaceId, enabled: Optional[bool] = None, configured: Optional[bool] = None
    ) -> List[CloudAccount]:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, id: FixCloudAccountId) -> None:
        raise NotImplementedError


class CloudAccountRepositoryImpl(CloudAccountRepository):
    def __init__(self, session_maker: AsyncSessionMaker) -> None:
        self.session_maker = session_maker

    async def create(self, cloud_account: CloudAccount) -> CloudAccount:
        """Create a cloud account."""
        async with self.session_maker() as session:
            if isinstance(cloud_account.access, AwsCloudAccess):
                orm_cloud_account = orm.CloudAccount(
                    id=cloud_account.id,
                    tenant_id=cloud_account.workspace_id,
                    cloud="aws",
                    account_id=cloud_account.access.aws_account_id,
                    aws_role_name=cloud_account.access.role_name,
                    aws_external_id=cloud_account.access.external_id,
                    name=cloud_account.name,
                    is_configured=cloud_account.is_configured,
                    enabled=cloud_account.enabled,
                )
            else:
                raise ValueError(f"Unknown cloud {cloud_account.access}")
            session.add(orm_cloud_account)
            await session.commit()
            await session.refresh(orm_cloud_account)
            return orm_cloud_account.to_model()

    async def get(self, id: FixCloudAccountId) -> Optional[CloudAccount]:
        """Get a single cloud account by id."""
        async with self.session_maker() as session:
            cloud_account = await session.get(orm.CloudAccount, id)
            return cloud_account.to_model() if cloud_account else None

    async def update(self, id: FixCloudAccountId, update_fn: Callable[[CloudAccount], CloudAccount]) -> CloudAccount:
        async with self.session_maker() as session:
            stored_account = await session.get(orm.CloudAccount, id)
            if stored_account is None:
                raise ResourceNotFound(f"Cloud account {id} not found")

            cloud_account = update_fn(stored_account.to_model())

            stored_account.name = cloud_account.name
            stored_account.is_configured = cloud_account.is_configured
            stored_account.enabled = cloud_account.enabled

            match cloud_account.access:
                case AwsCloudAccess(account_id, external_id, role_name):
                    stored_account.tenant_id = cloud_account.workspace_id
                    stored_account.cloud = "aws"
                    stored_account.account_id = account_id
                    stored_account.aws_external_id = external_id
                    stored_account.aws_role_name = role_name

                case _:
                    raise ValueError(f"Unknown cloud {cloud_account.access}")

            await session.commit()
            await session.refresh(stored_account)
            return stored_account.to_model()

    async def list_by_workspace_id(
        self, workspace_id: WorkspaceId, enabled: Optional[bool] = None, configured: Optional[bool] = None
    ) -> List[CloudAccount]:
        """Get a list of cloud accounts by tenant id."""
        async with self.session_maker() as session:
            statement = select(orm.CloudAccount).where(orm.CloudAccount.tenant_id == workspace_id)
            if enabled is not None:
                statement = statement.where(orm.CloudAccount.enabled == enabled)
            if configured is not None:
                statement = statement.where(orm.CloudAccount.is_configured == configured)
            results = await session.execute(statement)
            accounts = results.scalars().all()
            return [acc.to_model() for acc in accounts]

    async def delete(self, id: FixCloudAccountId) -> None:
        """Delete a cloud account."""
        async with self.session_maker() as session:
            statement = select(orm.CloudAccount).where(orm.CloudAccount.id == id)
            results = await session.execute(statement)
            cloud_account = results.unique().scalar_one()
            await session.delete(cloud_account)
            await session.commit()


def get_cloud_account_repository(session_maker: AsyncSessionMakerDependency) -> CloudAccountRepository:
    return CloudAccountRepositoryImpl(session_maker)


CloudAccountRepositoryDependency = Annotated[CloudAccountRepository, Depends(get_cloud_account_repository)]
