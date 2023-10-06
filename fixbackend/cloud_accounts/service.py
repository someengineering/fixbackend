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


import uuid
from abc import ABC, abstractmethod
from hmac import compare_digest
from typing import Annotated

from fastapi import Depends

from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount
from fixbackend.cloud_accounts.repository import CloudAccountRepository, CloudAccountRepositoryDependency
from fixbackend.ids import CloudAccountId, ExternalId, WorkspaceId
from fixbackend.organizations.repository import WorkspaceRepository, WorkspaceRepositoryDependency
from fixcloudutils.redis.event_stream import RedisStreamPublisher
from fixbackend.dependencies import FixDependency


class WrongExternalId(Exception):
    pass


class CloudAccountService(ABC):
    @abstractmethod
    async def create_aws_account(
        self, workspace_id: WorkspaceId, account_id: str, role_name: str, external_id: ExternalId
    ) -> CloudAccount:
        """Create a cloud account."""
        raise NotImplementedError

    @abstractmethod
    async def delete_cloud_account(self, cloud_accont_id: CloudAccountId, workspace_id: WorkspaceId) -> None:
        """Delete a cloud account."""
        raise NotImplementedError


class CloudAccountServiceImpl(CloudAccountService):
    def __init__(
        self,
        workspace_repository: WorkspaceRepository,
        cloud_account_repository: CloudAccountRepository,
        publisher: RedisStreamPublisher,
    ) -> None:
        self.workspace_repository = workspace_repository
        self.cloud_account_repository = cloud_account_repository
        self.publisher = publisher

    async def create_aws_account(
        self, workspace_id: WorkspaceId, account_id: str, role_name: str, external_id: ExternalId
    ) -> CloudAccount:
        """Create a cloud account."""

        organization = await self.workspace_repository.get_workspace(workspace_id)
        if organization is None:
            raise ValueError("Organization does not exist")
        if not compare_digest(str(organization.external_id), str(external_id)):
            raise WrongExternalId("External ids does not match")

        async def account_already_exists(workspace_id: WorkspaceId, account_id: str) -> bool:
            accounts = await self.cloud_account_repository.list_by_workspace_id(workspace_id)
            return any(
                account.access.account_id == account_id
                for account in accounts
                if isinstance(account.access, AwsCloudAccess)
            )

        if await account_already_exists(workspace_id, account_id):
            raise ValueError("Cloud account already exists")

        account = CloudAccount(
            id=CloudAccountId(uuid.uuid4()),
            workspace_id=workspace_id,
            access=AwsCloudAccess(account_id=account_id, external_id=external_id, role_name=role_name),
        )

        result = await self.cloud_account_repository.create(account)
        await self.publisher.publish("cloud_account_created", {"id": str(result.id)})
        return result

    async def delete_cloud_account(self, cloud_accont_id: CloudAccountId, workspace_id: WorkspaceId) -> None:
        account = await self.cloud_account_repository.get(cloud_accont_id)
        if not account or account.workspace_id != workspace_id:
            raise ValueError("Cloud account does not exist")

        await self.cloud_account_repository.delete(cloud_accont_id)
        await self.publisher.publish("cloud_account_deleted", {"id": str(cloud_accont_id)})


def get_cloud_account_service(
    workspace_repository_dependency: WorkspaceRepositoryDependency,
    cloud_account_repository_dependency: CloudAccountRepositoryDependency,
    fix_dependency: FixDependency,
) -> CloudAccountService:
    return CloudAccountServiceImpl(
        workspace_repository_dependency, cloud_account_repository_dependency, fix_dependency.cloudaccount_publisher
    )


CloudAccountServiceDependency = Annotated[CloudAccountService, Depends(get_cloud_account_service)]
