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
from datetime import datetime, timedelta
from typing import AsyncIterator, Dict, List, Optional

import pytest
from attrs import evolve
from fixcloudutils.util import utc
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.app import fast_api_app
from fixbackend.auth.depedencies import get_current_active_verified_user
from fixbackend.auth.models import User
from fixbackend.cloud_accounts.dependencies import get_cloud_account_service
from fixbackend.cloud_accounts.models import (
    AwsCloudAccess,
    CloudAccount,
    CloudAccountState,
    CloudAccountStates,
)
from fixbackend.cloud_accounts.service import CloudAccountService
from fixbackend.config import Config
from fixbackend.config import config as get_config
from fixbackend.db import get_async_session
from fixbackend.ids import (
    AwsRoleName,
    CloudAccountAlias,
    CloudAccountId,
    CloudAccountName,
    CloudNames,
    ExternalId,
    FixCloudAccountId,
    UserCloudAccountName,
    UserId,
    WorkspaceId,
    ProductTier,
)
from fixbackend.permissions.models import Roles, UserRole
from fixbackend.workspaces.dependencies import get_user_workspace
from fixbackend.workspaces.models import Workspace


class InMemoryCloudAccountService(CloudAccountService):
    def __init__(self) -> None:
        self.accounts: Dict[FixCloudAccountId, CloudAccount] = {}

    async def create_aws_account(
        self,
        *,
        workspace_id: WorkspaceId,
        account_id: CloudAccountId,
        role_name: Optional[AwsRoleName],
        external_id: ExternalId,
        account_name: Optional[CloudAccountName] = None,
    ) -> CloudAccount:
        assert role_name is not None
        account = CloudAccount(
            id=FixCloudAccountId(uuid.uuid4()),
            account_id=account_id,
            workspace_id=workspace_id,
            cloud=CloudNames.AWS,
            state=CloudAccountStates.Discovered(AwsCloudAccess(external_id, role_name), enabled=True),
            account_name=account_name,
            account_alias=None,
            user_account_name=None,
            privileged=False,
            last_scan_started_at=None,
            last_scan_duration_seconds=0,
            last_scan_resources_scanned=0,
            next_scan=None,
            created_at=utc(),
            updated_at=utc(),
            state_updated_at=utc(),
            cf_stack_version=0,
            failed_scan_count=0,
        )
        self.accounts[account.id] = account
        return account

    async def delete_cloud_account(
        self, user_id: UserId, cloud_account_id: FixCloudAccountId, workspace_id: WorkspaceId
    ) -> None:
        del self.accounts[cloud_account_id]

    async def get_cloud_account(self, cloud_account_id: FixCloudAccountId, workspace_id: WorkspaceId) -> CloudAccount:
        return self.accounts[cloud_account_id]

    async def list_accounts(self, workspace_id: WorkspaceId) -> List[CloudAccount]:
        return [acc for acc in self.accounts.values() if acc.workspace_id == workspace_id]

    async def update_cloud_account_name(
        self,
        workspace_id: WorkspaceId,
        cloud_account_id: FixCloudAccountId,
        name: Optional[UserCloudAccountName],
    ) -> CloudAccount:
        account = self.accounts[cloud_account_id]
        account = evolve(account, user_account_name=name)
        self.accounts[cloud_account_id] = account
        return account

    async def update_cloud_account_enabled(
        self, workspace_id: WorkspaceId, cloud_account_id: FixCloudAccountId, enabled: bool
    ) -> CloudAccount:
        account = self.accounts[cloud_account_id]
        match account.state:
            case CloudAccountStates.Configured():
                account = evolve(account, state=evolve(account.state, enabled=enabled))

        self.accounts[cloud_account_id] = account
        return account

    async def update_cloud_account_scan_enabled(
        self, workspace_id: WorkspaceId, cloud_account_id: FixCloudAccountId, scan: bool
    ) -> CloudAccount:
        account = self.accounts[cloud_account_id]
        match account.state:
            case CloudAccountStates.Configured():
                account = evolve(account, state=evolve(account.state, scan=scan))

        self.accounts[cloud_account_id] = account
        return account


cloud_account_service = InMemoryCloudAccountService()

workspace_id = WorkspaceId(uuid.uuid4())
external_id = ExternalId(uuid.uuid4())
workspace = Workspace(workspace_id, "foo", "foo", external_id, [], [], ProductTier.Free, utc(), utc())
role_name = AwsRoleName("FooBarRole")
account_id = CloudAccountId("123456789012")


@pytest.fixture
async def client(session: AsyncSession, default_config: Config, user: User) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app = fast_api_app(default_config)

    admin_user = evolve(user, roles=[UserRole(user.id, workspace_id, Roles.workspace_admin)])

    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_config] = lambda: default_config
    app.dependency_overrides[get_cloud_account_service] = lambda: cloud_account_service
    app.dependency_overrides[get_user_workspace] = lambda: workspace
    app.dependency_overrides[get_current_active_verified_user] = lambda: admin_user

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_aws_cloudformation_callback(client: AsyncClient) -> None:
    cloud_account_service.accounts = {}
    payload = {
        "account_id": account_id,
        "external_id": str(external_id),
        "role_name": role_name,
        "workspace_id": str(workspace_id),
        "fix_stack_version": 1708513196,
    }
    response = await client.post("/api/cloud/callbacks/aws/cf", json=payload)
    assert response.status_code == 200
    saved_account = list(cloud_account_service.accounts.values())[0]
    assert saved_account.workspace_id == workspace_id
    assert saved_account.account_id == account_id
    assert saved_account.cloud == "aws"
    assert saved_account.account_name is None
    assert saved_account.account_alias is None
    assert saved_account.user_account_name is None
    match saved_account.state:
        case CloudAccountStates.Discovered(AwsCloudAccess(e_id, r_name), enabled):
            assert e_id == external_id
            assert r_name == role_name
            assert enabled is True

        case _:
            assert False, "Unexpected state"


@pytest.mark.asyncio
async def test_delete_cloud_account(client: AsyncClient) -> None:
    cloud_account_service.accounts = {}
    cloud_account_id = FixCloudAccountId(uuid.uuid4())
    cloud_account_service.accounts[cloud_account_id] = CloudAccount(
        id=cloud_account_id,
        account_id=account_id,
        cloud=CloudNames.AWS,
        workspace_id=workspace_id,
        state=CloudAccountStates.Detected(),
        account_name=CloudAccountName("foo"),
        account_alias=None,
        user_account_name=None,
        privileged=False,
        last_scan_started_at=None,
        last_scan_duration_seconds=0,
        last_scan_resources_scanned=0,
        next_scan=None,
        created_at=utc(),
        updated_at=utc(),
        state_updated_at=utc(),
        cf_stack_version=0,
        failed_scan_count=0,
    )
    response = await client.delete(f"/api/workspaces/{workspace_id}/cloud_account/{cloud_account_id}")
    assert response.status_code == 200
    assert len(cloud_account_service.accounts) == 0


@pytest.mark.asyncio
async def test_last_scan(client: AsyncClient) -> None:
    next_scan = datetime.utcnow()
    started_at = datetime.utcnow()

    cloud_account_service.accounts = {}
    cloud_account_id = FixCloudAccountId(uuid.uuid4())
    cloud_account_service.accounts[cloud_account_id] = CloudAccount(
        id=cloud_account_id,
        account_id=CloudAccountId("123456789012"),
        cloud=CloudNames.AWS,
        workspace_id=workspace_id,
        state=CloudAccountStates.Detected(),
        account_name=CloudAccountName("foo"),
        account_alias=None,
        user_account_name=None,
        privileged=False,
        last_scan_started_at=started_at,
        last_scan_duration_seconds=10,
        last_scan_resources_scanned=100,
        next_scan=next_scan,
        created_at=utc(),
        updated_at=utc(),
        state_updated_at=utc(),
        cf_stack_version=0,
        failed_scan_count=0,
    )

    response = await client.get(f"/api/workspaces/{workspace_id}/cloud_accounts/last_scan")
    assert response.status_code == 200
    data = response.json()
    assert data["workspace_id"] == str(workspace_id)
    assert len(data["accounts"]) == 1
    assert data["accounts"][0]["account_id"] == "123456789012"
    assert data["accounts"][0]["duration"] == 10
    assert data["accounts"][0]["resource_scanned"] == 100
    assert data["accounts"][0]["started_at"] == started_at.isoformat()
    assert data["next_scan"] == next_scan.isoformat()


@pytest.mark.asyncio
async def test_get_cloud_account(client: AsyncClient) -> None:
    cloud_account_service.accounts = {}
    cloud_account_id = FixCloudAccountId(uuid.uuid4())
    next_scan = datetime.utcnow()
    started_at = datetime.utcnow()
    cloud_account_service.accounts[cloud_account_id] = CloudAccount(
        id=cloud_account_id,
        account_id=account_id,
        workspace_id=workspace_id,
        cloud=CloudNames.AWS,
        state=CloudAccountStates.Configured(AwsCloudAccess(external_id, role_name), enabled=True, scan=True),
        account_name=CloudAccountName("foo"),
        account_alias=CloudAccountAlias("foo_alias"),
        user_account_name=UserCloudAccountName("foo_user"),
        privileged=True,
        last_scan_duration_seconds=10,
        last_scan_resources_scanned=100,
        last_scan_started_at=started_at,
        next_scan=next_scan,
        created_at=utc(),
        updated_at=utc(),
        state_updated_at=utc(),
        cf_stack_version=42,
        failed_scan_count=0,
    )

    response = await client.get(f"/api/workspaces/{workspace_id}/cloud_account/{cloud_account_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(cloud_account_id)
    assert data["cloud"] == "aws"
    assert data["account_id"] == "123456789012"
    assert data["api_account_alias"] == "foo_alias"
    assert data["api_account_name"] == "foo"
    assert data["user_account_name"] == "foo_user"
    assert data["is_configured"] is True
    assert data["enabled"] is True
    assert data["resources"] == 100
    assert data["next_scan"] == next_scan.isoformat()
    assert data["state"] == "configured"
    assert data["privileged"] is True
    assert data["last_scan_started_at"] == started_at.isoformat()
    assert data["last_scan_finished_at"] == (started_at + timedelta(seconds=10)).isoformat()
    assert data["cf_stack_version"] == 42


@pytest.mark.asyncio
async def test_list_cloud_accounts(client: AsyncClient) -> None:
    cloud_account_service.accounts = {}

    def add_account(created_at: datetime, state: CloudAccountState) -> CloudAccount:
        cloud_account_id = FixCloudAccountId(uuid.uuid4())
        next_scan = utc()
        account = CloudAccount(
            id=cloud_account_id,
            account_id=account_id,
            workspace_id=workspace_id,
            cloud=CloudNames.AWS,
            state=state,
            account_name=CloudAccountName("foo"),
            account_alias=CloudAccountAlias("foo_alias"),
            user_account_name=UserCloudAccountName("foo_user"),
            privileged=True,
            last_scan_duration_seconds=10,
            last_scan_resources_scanned=100,
            last_scan_started_at=utc(),
            next_scan=next_scan,
            created_at=created_at,
            updated_at=utc(),
            state_updated_at=utc(),
            cf_stack_version=0,
            failed_scan_count=0,
        )
        cloud_account_service.accounts[cloud_account_id] = account
        return account

    def check_account(data: Dict[str, str], account: CloudAccount) -> None:
        assert data["id"] == str(account.id)
        assert data["cloud"] == account.cloud
        assert data["account_id"] == account.account_id
        assert data["state"] == account.state.state_name
        assert int(data["resources"]) == account.last_scan_resources_scanned
        assert data["api_account_alias"] == account.account_alias
        assert data["api_account_name"] == account.account_name
        assert data["user_account_name"] == account.user_account_name

    configured_state = CloudAccountStates.Configured(AwsCloudAccess(external_id, role_name), enabled=True, scan=True)

    recent = add_account(utc(), configured_state)
    added = add_account(utc() - timedelta(days=2), configured_state)
    detected = add_account(utc(), CloudAccountStates.Detected())
    recent_discovered = add_account(
        utc() - timedelta(minutes=1),
        CloudAccountStates.Discovered(AwsCloudAccess(external_id, role_name), enabled=True),
    )
    recent_degraded = add_account(
        utc() - timedelta(minutes=3), CloudAccountStates.Degraded(AwsCloudAccess(external_id, role_name), "foo")
    )

    response = await client.get(f"/api/workspaces/{workspace_id}/cloud_accounts")
    assert response.status_code == 200
    data = response.json()

    recent_accounts = data.get("recent")
    assert recent_accounts is not None
    assert len(recent_accounts) == 3
    check_account(recent_accounts[0], recent)
    check_account(recent_accounts[1], recent_discovered)
    check_account(recent_accounts[2], recent_degraded)

    added_accounts = data.get("added")
    assert added_accounts is not None
    assert len(added_accounts) == 1
    check_account(added_accounts[0], added)

    discovered_accounts = data.get("discovered")
    assert discovered_accounts is not None
    assert len(discovered_accounts) == 1
    check_account(discovered_accounts[0], detected)


@pytest.mark.asyncio
async def test_update_cloud_account(client: AsyncClient) -> None:
    cloud_account_service.accounts = {}
    cloud_account_id = FixCloudAccountId(uuid.uuid4())
    next_scan = datetime.utcnow()
    cloud_account_service.accounts[cloud_account_id] = CloudAccount(
        id=cloud_account_id,
        workspace_id=workspace_id,
        account_id=account_id,
        cloud=CloudNames.AWS,
        state=CloudAccountStates.Configured(AwsCloudAccess(external_id, role_name), enabled=True, scan=True),
        account_name=CloudAccountName("foo"),
        account_alias=CloudAccountAlias("foo_alias"),
        user_account_name=UserCloudAccountName("foo_user"),
        privileged=False,
        last_scan_duration_seconds=10,
        last_scan_resources_scanned=100,
        last_scan_started_at=datetime.utcnow(),
        next_scan=next_scan,
        created_at=utc(),
        updated_at=utc(),
        state_updated_at=utc(),
        cf_stack_version=0,
        failed_scan_count=0,
    )

    payload: Dict[str, Optional[str]] = {
        "name": "bar",
    }
    response = await client.patch(f"/api/workspaces/{workspace_id}/cloud_account/{cloud_account_id}", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(cloud_account_id)
    assert data["cloud"] == "aws"
    assert data["account_id"] == "123456789012"
    assert data["user_account_name"] == "bar"
    assert data["resources"] == 100
    assert data["next_scan"] == next_scan.isoformat()

    # set name to None
    payload = {
        "name": None,
    }
    response = await client.patch(f"/api/workspaces/{workspace_id}/cloud_account/{cloud_account_id}", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["user_account_name"] is None


@pytest.mark.asyncio
async def test_enable_disable_account(client: AsyncClient) -> None:
    cloud_account_service.accounts = {}
    cloud_account_id = FixCloudAccountId(uuid.uuid4())
    next_scan = datetime.utcnow()
    cloud_account_service.accounts[cloud_account_id] = CloudAccount(
        id=cloud_account_id,
        workspace_id=workspace_id,
        account_id=account_id,
        cloud=CloudNames.AWS,
        state=CloudAccountStates.Configured(AwsCloudAccess(external_id, role_name), enabled=True, scan=True),
        account_name=CloudAccountName("foo"),
        account_alias=CloudAccountAlias("foo_alias"),
        user_account_name=UserCloudAccountName("foo_user"),
        privileged=True,
        last_scan_duration_seconds=10,
        last_scan_resources_scanned=100,
        last_scan_started_at=utc(),
        next_scan=next_scan,
        created_at=utc(),
        updated_at=utc(),
        state_updated_at=utc(),
        cf_stack_version=0,
        failed_scan_count=0,
    )

    response = await client.patch(f"/api/workspaces/{workspace_id}/cloud_account/{cloud_account_id}/disable")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(cloud_account_id)
    assert data["cloud"] == "aws"
    assert data["account_id"] == "123456789012"
    assert data["user_account_name"] == "foo_user"
    assert data["enabled"] is False
    assert data["is_configured"] is True
    assert data["resources"] == 100
    assert data["next_scan"] == next_scan.isoformat()

    response = await client.patch(f"/api/workspaces/{workspace_id}/cloud_account/{cloud_account_id}/enable")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(cloud_account_id)
    assert data["cloud"] == "aws"
    assert data["account_id"] == "123456789012"
    assert data["user_account_name"] == "foo_user"
    assert data["enabled"] is True
    assert data["is_configured"] is True
    assert data["resources"] == 100
    assert data["next_scan"] == next_scan.isoformat()


@pytest.mark.asyncio
async def test_enable_disable_account_scan(client: AsyncClient) -> None:
    cloud_account_service.accounts = {}
    cloud_account_id = FixCloudAccountId(uuid.uuid4())
    cloud_account_service.accounts[cloud_account_id] = CloudAccount(
        id=cloud_account_id,
        workspace_id=workspace_id,
        account_id=account_id,
        cloud=CloudNames.AWS,
        state=CloudAccountStates.Configured(AwsCloudAccess(external_id, role_name), enabled=True, scan=True),
        account_name=CloudAccountName("foo"),
        account_alias=CloudAccountAlias("foo_alias"),
        user_account_name=UserCloudAccountName("foo_user"),
        privileged=True,
        last_scan_duration_seconds=10,
        last_scan_resources_scanned=100,
        last_scan_started_at=utc(),
        next_scan=utc(),
        created_at=utc(),
        updated_at=utc(),
        state_updated_at=utc(),
        cf_stack_version=None,
        failed_scan_count=0,
    )

    response = await client.patch(f"/api/workspaces/{workspace_id}/cloud_account/{cloud_account_id}/scan/disable")
    assert response.status_code == 200
    data = response.json()
    assert data["scan"] is False

    response = await client.patch(f"/api/workspaces/{workspace_id}/cloud_account/{cloud_account_id}/scan/enable")
    assert response.status_code == 200
    data = response.json()
    assert data["scan"] is True
