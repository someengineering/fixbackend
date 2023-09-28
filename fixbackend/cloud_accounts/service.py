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
from hmac import compare_digest
from typing import Annotated

from fastapi import Depends

from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount
from fixbackend.cloud_accounts.repository import CloudAccountRepository, CloudAccountRepositoryDependency
from fixbackend.ids import CloudAccountId, ExternalId, TenantId
from fixbackend.organizations.dependencies import OrganizationServiceDependency
from fixbackend.organizations.service import OrganizationService


class WrongExternalId(Exception):
    pass


class CloudAccountService:
    def __init__(
        self,
        organization_service: OrganizationService,
        cloud_account_repository: CloudAccountRepository,
    ) -> None:
        self.organization_service = organization_service
        self.cloud_account_repository = cloud_account_repository

    async def create_aws_account(
        self, tenant_id: TenantId, account_id: str, role_name: str, external_id: ExternalId
    ) -> CloudAccount:
        """Create a cloud account."""

        organization = await self.organization_service.get_organization(tenant_id)
        if organization is None:
            raise ValueError("Organization does not exist")
        if not compare_digest(str(organization.external_id), str(external_id)):
            raise WrongExternalId("External ids does not match")

        account = CloudAccount(
            id=CloudAccountId(uuid.uuid4()),
            tenant_id=tenant_id,
            access=AwsCloudAccess(account_id=account_id, external_id=external_id, role_name=role_name),
        )

        result = await self.cloud_account_repository.create(account)
        # await self.publisher.publish("cloud_account_created", {"id": str(result.id)})
        return result

    async def delete_cloud_account(self, cloud_accont_id: CloudAccountId) -> None:
        await self.cloud_account_repository.delete(cloud_accont_id)


def get_cloud_account_service(
    organization_service_dependency: OrganizationServiceDependency,
    cloud_account_repository_dependency: CloudAccountRepositoryDependency,
) -> CloudAccountService:
    return CloudAccountService(
        organization_service_dependency,
        cloud_account_repository_dependency,
    )


CloudAccountServiceDependency = Annotated[CloudAccountService, Depends(get_cloud_account_service)]
