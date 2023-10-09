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
from typing import AsyncIterator, List

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.app import fast_api_app
from fixbackend.auth.current_user_dependencies import get_user_workspaces_ids
from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount
from fixbackend.cloud_accounts.service import CloudAccountService, get_cloud_account_service
from fixbackend.config import Config
from fixbackend.config import config as get_config
from fixbackend.db import get_async_session
from fixbackend.ids import CloudAccountId, ExternalId, WorkspaceId


class InMemoryCloudAccountService(CloudAccountService):
    def __init__(self) -> None:
        self.accounts: List[CloudAccount] = []

    async def create_aws_account(
        self, workspace_id: WorkspaceId, account_id: str, role_name: str, external_id: ExternalId
    ) -> CloudAccount:
        account = CloudAccount(
            id=CloudAccountId(uuid.uuid4()),
            workspace_id=workspace_id,
            access=AwsCloudAccess(account_id, external_id, role_name),
        )
        self.accounts.append(account)
        return account

    async def delete_cloud_account(self, cloud_account_id: CloudAccountId, workspace_id: WorkspaceId) -> None:
        self.accounts = [account for account in self.accounts if account.id != cloud_account_id]


cloud_account_service = InMemoryCloudAccountService()

workspace_id = WorkspaceId(uuid.uuid4())
external_id = ExternalId(uuid.uuid4())
role_name = "FooBarRole"
account_id = "123456789012"


@pytest.fixture
async def client(session: AsyncSession, default_config: Config) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app = fast_api_app(default_config)

    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_config] = lambda: default_config
    app.dependency_overrides[get_cloud_account_service] = lambda: cloud_account_service
    app.dependency_overrides[get_user_workspaces_ids] = lambda: {workspace_id}

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_aws_cloudformation_callback(client: AsyncClient) -> None:
    cloud_account_service.accounts = []
    payload = {
        "account_id": account_id,
        "external_id": str(external_id),
        "role_name": role_name,
        "workspace_id": str(workspace_id),
    }
    response = await client.post("/api/cloud/callbacks/aws/cf", json=payload)
    assert response.status_code == 200
    saved_account = cloud_account_service.accounts[0]
    assert saved_account.workspace_id == workspace_id
    match saved_account.access:
        case AwsCloudAccess(a_id, e_id, r_name):
            assert a_id == account_id
            assert e_id == external_id
            assert r_name == role_name


@pytest.mark.asyncio
async def test_delete_cloud_account(client: AsyncClient) -> None:
    cloud_account_service.accounts = []
    cloud_account_id = CloudAccountId(uuid.uuid4())
    cloud_account_service.accounts.append(
        CloudAccount(
            id=cloud_account_id,
            workspace_id=workspace_id,
            access=AwsCloudAccess(account_id, external_id, role_name),
        )
    )
    response = await client.delete(f"/api/workspaces/{workspace_id}/cloud_account/{cloud_account_id}")
    assert response.status_code == 200
    assert len(cloud_account_service.accounts) == 0

    # deleting an account in a wrong workspace should fail
    response = await client.delete(f"/api/workspaces/{WorkspaceId(uuid.uuid4())}/cloud_account/{cloud_account_id}")
    assert response.status_code == 403
