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
from fixcloudutils.redis.event_stream import RedisStreamPublisher
from fixcloudutils.redis.pub_sub import RedisPubSubPublisher

from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount
from fixbackend.cloud_accounts.repository import CloudAccountRepository, CloudAccountRepositoryDependency
from fixbackend.dependencies import FixDependency
from fixbackend.ids import CloudAccountId, ExternalId, TenantId
from fixbackend.organizations.repository import OrganizationRepository, OrganizationRepositoryDependency


class WrongExternalId(Exception):
    pass


class CloudAccountService(ABC):
    @abstractmethod
    async def create_aws_account(
        self, tenant_id: TenantId, account_id: str, role_name: str, external_id: ExternalId
    ) -> CloudAccount:
        """Create a cloud account."""
        raise NotImplementedError

    @abstractmethod
    async def delete_cloud_account(self, cloud_account_id: CloudAccountId, tenant_id: TenantId) -> None:
        """Delete a cloud account."""
        raise NotImplementedError


class CloudAccountServiceImpl(CloudAccountService):
    def __init__(
        self,
        organization_service: OrganizationRepository,
        cloud_account_repository: CloudAccountRepository,
        publisher: RedisStreamPublisher,
        pubsub_publisher: RedisPubSubPublisher,
    ) -> None:
        self.organization_service = organization_service
        self.cloud_account_repository = cloud_account_repository
        self.publisher = publisher
        self.pubsub_publisher = pubsub_publisher

    async def create_aws_account(
        self, tenant_id: TenantId, account_id: str, role_name: str, external_id: ExternalId
    ) -> CloudAccount:
        """Create a cloud account."""

        organization = await self.organization_service.get_organization(tenant_id)
        if organization is None:
            raise ValueError("Organization does not exist")
        if not compare_digest(str(organization.external_id), str(external_id)):
            raise WrongExternalId("External ids does not match")

        async def account_already_exists(tenant_id: TenantId, account_id: str) -> bool:
            accounts = await self.cloud_account_repository.list_by_tenant_id(tenant_id)
            return any(
                account.access.account_id == account_id
                for account in accounts
                if isinstance(account.access, AwsCloudAccess)
            )

        if await account_already_exists(tenant_id, account_id):
            raise ValueError("Cloud account already exists")

        account = CloudAccount(
            id=CloudAccountId(uuid.uuid4()),
            tenant_id=tenant_id,
            access=AwsCloudAccess(account_id=account_id, external_id=external_id, role_name=role_name),
        )

        result = await self.cloud_account_repository.create(account)
        message = {
            "cloud_account_id": str(result.id),
            "tenant_id": str(result.tenant_id),
            "aws_account_id": account_id,
        }
        await self.publisher.publish(kind="cloud_account_created", message=message)
        await self.pubsub_publisher.publish(
            kind="cloud_account_created", message=message, channel=f"tenant-events::{tenant_id}"
        )
        return result

    async def delete_cloud_account(self, cloud_account_id: CloudAccountId, tenant_id: TenantId) -> None:
        account = await self.cloud_account_repository.get(cloud_account_id)
        if not account or account.tenant_id != tenant_id:
            raise ValueError("Cloud account does not exist")

        await self.cloud_account_repository.delete(cloud_account_id)
        await self.publisher.publish("cloud_account_deleted", {"id": str(cloud_account_id)})


def get_cloud_account_service(
    organization_service_dependency: OrganizationRepositoryDependency,
    cloud_account_repository_dependency: CloudAccountRepositoryDependency,
    fix_dependency: FixDependency,
) -> CloudAccountService:
    redis_publisher = RedisPubSubPublisher(
        redis=fix_dependency.readwrite_redis, channel="cloud_accounts", publisher_name="cloud_account_service"
    )
    return CloudAccountServiceImpl(
        organization_service_dependency,
        cloud_account_repository_dependency,
        fix_dependency.cloudaccount_publisher,
        redis_publisher,
    )


CloudAccountServiceDependency = Annotated[CloudAccountService, Depends(get_cloud_account_service)]
