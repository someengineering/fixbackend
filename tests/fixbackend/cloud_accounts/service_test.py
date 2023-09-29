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
from typing import Dict, List, Optional, Tuple

import pytest

from fixbackend.cloud_accounts.models import CloudAccount, AwsCloudAccess
from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.cloud_accounts.service import CloudAccountServiceImpl
from fixbackend.ids import CloudAccountId, ExternalId, TenantId
from fixbackend.organizations.models import Organization
from fixbackend.organizations.service import OrganizationService
from fixcloudutils.redis.event_stream import RedisStreamPublisher
from fixcloudutils.types import Json


class CloudAccountRepositoryMock(CloudAccountRepository):
    def __init__(self) -> None:
        self.accounts: Dict[CloudAccountId, CloudAccount] = {}

    async def create(self, cloud_account: CloudAccount) -> CloudAccount:
        self.accounts[cloud_account.id] = cloud_account
        return cloud_account

    async def get(self, id: CloudAccountId) -> CloudAccount | None:
        return self.accounts.get(id)

    async def list_by_tenant_id(self, tenant_id: TenantId) -> List[CloudAccount]:
        return [account for account in self.accounts.values() if account.tenant_id == tenant_id]

    async def delete(self, id: CloudAccountId) -> None:
        self.accounts.pop(id)


tenant_id = TenantId(uuid.uuid4())

account_id = "foobar"
role_name = "FooBarRole"
external_id = ExternalId(uuid.uuid4())

organization = Organization(
    id=tenant_id,
    name="Test Organization",
    slug="test-organization",
    external_id=external_id,
    owners=[],
    members=[],
)


class OrganizationServiceMock(OrganizationService):
    def __init__(self) -> None:
        pass

    async def get_organization(self, organization_id: TenantId, with_users: bool = False) -> Organization | None:
        if organization_id != tenant_id:
            return None
        return organization


class RedisPublisherMock(RedisStreamPublisher):
    def __init__(self) -> None:
        self.last_message: Optional[Tuple[str, Json]] = None

    async def publish(self, kind: str, message: Json) -> None:
        self.last_message = (kind, message)


@pytest.mark.asyncio
async def test_create_aws_account() -> None:
    repository = CloudAccountRepositoryMock()
    organisation_service = OrganizationServiceMock()
    publisher = RedisPublisherMock()
    service = CloudAccountServiceImpl(organisation_service, repository, publisher)

    # happy case
    acc = await service.create_aws_account(tenant_id, account_id, role_name, external_id)
    assert len(repository.accounts) == 1
    account = repository.accounts.get(acc.id)
    assert account is not None
    assert account.tenant_id == tenant_id
    assert isinstance(account.access, AwsCloudAccess)
    assert account.access.account_id == account_id
    assert account.access.role_name == role_name
    assert account.access.external_id == external_id

    assert publisher.last_message is not None
    assert publisher.last_message[0] == "cloud_account_created"
    assert publisher.last_message[1] == {"id": str(account.id)}

    # account already exists
    with pytest.raises(Exception):
        await service.create_aws_account(tenant_id, account_id, role_name, external_id)

    # wrong external id
    with pytest.raises(Exception):
        await service.create_aws_account(tenant_id, account_id, role_name, ExternalId(uuid.uuid4()))

    # wrong tenant id
    with pytest.raises(Exception):
        await service.create_aws_account(TenantId(uuid.uuid4()), account_id, role_name, external_id)


@pytest.mark.asyncio
async def test_delete_aws_account() -> None:
    repository = CloudAccountRepositoryMock()
    organisation_service = OrganizationServiceMock()
    publisher = RedisPublisherMock()
    service = CloudAccountServiceImpl(organisation_service, repository, publisher)

    account = await service.create_aws_account(tenant_id, account_id, role_name, external_id)
    assert len(repository.accounts) == 1

    # deleting someone's else account
    with pytest.raises(Exception):
        await service.delete_cloud_account(account.id, TenantId(uuid.uuid4()))
    assert len(repository.accounts) == 1

    # success
    await service.delete_cloud_account(account.id, tenant_id)
    assert len(repository.accounts) == 0

    assert publisher.last_message is not None
    assert publisher.last_message[0] == "cloud_account_deleted"
    assert publisher.last_message[1] == {"id": str(account.id)}
