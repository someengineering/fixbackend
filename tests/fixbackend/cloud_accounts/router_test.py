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


from typing import AsyncIterator, List

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.app import fast_api_app
from fixbackend.cloud_accounts.models import CloudAccount, AwsCloudAccess
from fixbackend.cloud_accounts.service import CloudAccountService, get_cloud_account_service
from fixbackend.config import Config
from fixbackend.config import config as get_config
from fixbackend.db import get_async_session
from fixbackend.ids import CloudAccountId, ExternalId, TenantId
import uuid


class InMemoryCloudAccontService(CloudAccountService):
    def __init__(self) -> None:
        self.accounts: List[CloudAccount] = []

    async def create_aws_account(
        self, tenant_id: TenantId, account_id: str, role_name: str, external_id: ExternalId
    ) -> CloudAccount:
        account = CloudAccount(
            id=CloudAccountId(uuid.uuid4()),
            tenant_id=tenant_id,
            access=AwsCloudAccess(account_id, external_id, role_name),
        )
        self.accounts.append(account)
        return account


cloud_accont_service = InMemoryCloudAccontService()

tenant_id = TenantId(uuid.uuid4())
external_id = ExternalId(uuid.uuid4())
role_name = "FooBarRole"
account_id = "123456789012"


@pytest.fixture
async def client(session: AsyncSession, default_config: Config) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app = fast_api_app(default_config)

    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_config] = lambda: default_config
    app.dependency_overrides[get_cloud_account_service] = lambda: cloud_accont_service

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_aws_cloudformation_callback(client: AsyncClient) -> None:
    payload = {
        "account_id": account_id,
        "external_id": str(external_id),
        "role_name": role_name,
        "tenant_id": str(tenant_id),
    }
    response = await client.post("/api/cloud/callbacks/aws/cf", json=payload)
    assert response.status_code == 200
    saved_account = cloud_accont_service.accounts[0]
    assert saved_account.tenant_id == tenant_id
    match saved_account.access:
        case AwsCloudAccess(a_id, e_id, r_name):
            assert a_id == account_id
            assert e_id == external_id
            assert r_name == role_name
