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
from sqlalchemy.orm.exc import StaleDataError
from fixcloudutils.util import utc

from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount, CloudAccountState, CloudAccountStates, orm
from fixbackend.db import AsyncSessionMakerDependency
from fixbackend.errors import ResourceNotFound
from fixbackend.ids import AwsRoleName, ExternalId, FixCloudAccountId, ProductTier, WorkspaceId
from fixbackend.types import AsyncSessionMaker
from fixbackend.workspaces.models.orm import Organization


class CloudAccountRepository(ABC):
    @abstractmethod
    async def create(self, cloud_account: CloudAccount) -> CloudAccount:
        raise NotImplementedError

    @abstractmethod
    async def get(self, id: FixCloudAccountId) -> Optional[CloudAccount]:
        raise NotImplementedError

    @abstractmethod
    async def list(self, ids: List[FixCloudAccountId]) -> List[CloudAccount]:
        raise NotImplementedError

    @abstractmethod
    async def update(self, id: FixCloudAccountId, update_fn: Callable[[CloudAccount], CloudAccount]) -> CloudAccount:
        raise NotImplementedError

    @abstractmethod
    async def list_by_workspace_id(
        self, workspace_id: WorkspaceId, ready_for_collection: Optional[bool] = None, non_deleted: Optional[bool] = None
    ) -> List[CloudAccount]:
        raise NotImplementedError

    @abstractmethod
    async def list_all_discovered_accounts(self) -> List[CloudAccount]:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, id: FixCloudAccountId) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_non_hourly_failed_scans_accounts(self) -> List[CloudAccount]:
        raise NotImplementedError


class CloudAccountRepositoryImpl(CloudAccountRepository):
    def __init__(self, session_maker: AsyncSessionMaker) -> None:
        self.session_maker = session_maker

    def _update_state_dependent_fields(
        self, orm_cloud_account: orm.CloudAccount, account_state: CloudAccountState
    ) -> None:
        role_name: Optional[AwsRoleName] = None
        external_id: Optional[ExternalId] = None
        enabled = False
        scan = False
        error: Optional[str] = None
        state: Optional[str] = None
        match account_state:
            case CloudAccountStates.Detected():
                state = CloudAccountStates.Detected.state_name

            case CloudAccountStates.Discovered(AwsCloudAccess(external_id, role_name)):
                role_name = role_name
                external_id = external_id
                state = CloudAccountStates.Discovered.state_name

            case CloudAccountStates.Configured(AwsCloudAccess(external_id, role_name), ex_enabled, ex_scan):
                external_id = external_id
                enabled = ex_enabled
                scan = ex_scan
                state = CloudAccountStates.Configured.state_name

            case CloudAccountStates.Degraded(AwsCloudAccess(external_id, role_name), error):
                external_id = external_id
                role_name = role_name
                error = error
                state = CloudAccountStates.Degraded.state_name

            case CloudAccountStates.Deleted():
                external_id = None
                role_name = None
                state = CloudAccountStates.Deleted.state_name

            case _:
                raise ValueError(f"Unknown state {account_state}")

        orm_cloud_account.aws_external_id = external_id
        orm_cloud_account.aws_role_name = role_name
        orm_cloud_account.state = state
        orm_cloud_account.error = error
        orm_cloud_account.enabled = enabled
        orm_cloud_account.scan = scan

    async def create(self, cloud_account: CloudAccount) -> CloudAccount:
        """Create a cloud account."""
        async with self.session_maker() as session:
            if cloud_account.cloud != "aws":
                raise ValueError(f"Unknown cloud {cloud_account.cloud}")

            orm_cloud_account = orm.CloudAccount(
                id=cloud_account.id,
                tenant_id=cloud_account.workspace_id,
                cloud=cloud_account.cloud,
                account_id=cloud_account.account_id,
                user_account_name=cloud_account.user_account_name,
                api_account_name=cloud_account.account_name,
                api_account_alias=cloud_account.account_alias,
                is_configured=False,  # to keep backwards compatibility, remove in the next release
                privileged=cloud_account.privileged,
                created_at=cloud_account.created_at,
                updated_at=cloud_account.updated_at,
                state_updated_at=cloud_account.state_updated_at,
                cf_stack_version=cloud_account.cf_stack_version,
                failed_scan_count=cloud_account.failed_scan_count,
            )
            self._update_state_dependent_fields(orm_cloud_account, cloud_account.state)
            session.add(orm_cloud_account)
            await session.commit()
            await session.refresh(orm_cloud_account)
            return orm_cloud_account.to_model()

    async def get(self, id: FixCloudAccountId) -> Optional[CloudAccount]:
        """Get a single cloud account by id."""
        async with self.session_maker() as session:
            cloud_account = await session.get(orm.CloudAccount, id)
            return cloud_account.to_model() if cloud_account else None

    async def list(self, ids: List[FixCloudAccountId]) -> List[CloudAccount]:
        """Get a list of cloud accounts by ids."""
        async with self.session_maker() as session:
            statement = select(orm.CloudAccount).where(orm.CloudAccount.id.in_(ids))
            results = await session.execute(statement)
            accounts = results.scalars().all()
            return [acc.to_model() for acc in accounts]

    async def update(self, id: FixCloudAccountId, update_fn: Callable[[CloudAccount], CloudAccount]) -> CloudAccount:
        async def do_updade() -> CloudAccount:
            async with self.session_maker() as session:
                stored_account = await session.get(orm.CloudAccount, id)
                if stored_account is None:
                    raise ResourceNotFound(f"Cloud account {id} not found")

                cloud_account = update_fn(stored_account.to_model())

                if stored_account.to_model() == cloud_account:
                    # nothing to update
                    return cloud_account

                stored_account.tenant_id = cloud_account.workspace_id
                stored_account.cloud = cloud_account.cloud
                stored_account.account_id = cloud_account.account_id
                stored_account.api_account_name = cloud_account.account_name
                stored_account.api_account_alias = cloud_account.account_alias
                stored_account.user_account_name = cloud_account.user_account_name
                stored_account.privileged = cloud_account.privileged
                stored_account.next_scan = cloud_account.next_scan
                stored_account.last_scan_duration_seconds = cloud_account.last_scan_duration_seconds
                stored_account.last_scan_started_at = cloud_account.last_scan_started_at
                stored_account.last_scan_resources_scanned = cloud_account.last_scan_resources_scanned
                stored_account.created_at = cloud_account.created_at
                stored_account.updated_at = utc()
                stored_account.state_updated_at = cloud_account.state_updated_at
                stored_account.cf_stack_version = cloud_account.cf_stack_version
                stored_account.failed_scan_count = cloud_account.failed_scan_count
                self._update_state_dependent_fields(stored_account, cloud_account.state)

                await session.commit()
                await session.refresh(stored_account)
                return stored_account.to_model()

        while True:
            try:
                return await do_updade()
            except StaleDataError:  # in case of concurrent update
                pass

    async def list_by_workspace_id(
        self, workspace_id: WorkspaceId, ready_for_collection: Optional[bool] = None, non_deleted: Optional[bool] = None
    ) -> List[CloudAccount]:
        """Get a list of cloud accounts by tenant id."""
        async with self.session_maker() as session:
            statement = select(orm.CloudAccount).where(orm.CloudAccount.tenant_id == workspace_id)
            if ready_for_collection is not None and ready_for_collection:
                statement = statement.where(orm.CloudAccount.state == CloudAccountStates.Configured.state_name).where(
                    orm.CloudAccount.enabled.is_(True)
                )
            if non_deleted is not None and non_deleted:
                statement = statement.where(orm.CloudAccount.state != CloudAccountStates.Deleted.state_name)
            results = await session.execute(statement)
            accounts = results.scalars().all()
            return [acc.to_model() for acc in accounts]

    async def list_all_discovered_accounts(self) -> List[CloudAccount]:
        """Get a list of all discovered cloud accounts."""
        async with self.session_maker() as session:
            statement = select(orm.CloudAccount).where(
                orm.CloudAccount.state == CloudAccountStates.Discovered.state_name
            )
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

    async def list_non_hourly_failed_scans_accounts(self) -> List[CloudAccount]:
        async with self.session_maker() as session:
            # select all accounts that are enabled and in the configured state
            # join with the workspaces where the workspace product_tier is not business or enterprise

            statement = (
                select(orm.CloudAccount)
                .join(Organization, orm.CloudAccount.tenant_id == Organization.id)
                .where(orm.CloudAccount.enabled.is_(True))
                .where(orm.CloudAccount.state == CloudAccountStates.Configured.state_name)
                .where(orm.CloudAccount.failed_scan_count > 0)
                .where(Organization.tier.notin_([ProductTier.Enterprise, ProductTier.Business, ProductTier.Trial]))
            )

            results = await session.execute(statement)
            accounts = results.scalars().all()
            return [acc.to_model() for acc in accounts]


def get_cloud_account_repository(session_maker: AsyncSessionMakerDependency) -> CloudAccountRepository:
    return CloudAccountRepositoryImpl(session_maker)


CloudAccountRepositoryDependency = Annotated[CloudAccountRepository, Depends(get_cloud_account_repository)]
