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


from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from fixcloudutils.util import utc
from httpx import AsyncClient

from fixbackend.auth.depedencies import get_current_active_verified_user, maybe_current_active_verified_user
from fixbackend.auth.models import User
from fixbackend.config import Config
from fixbackend.ids import UserId, WorkspaceId, ProductTier, ExternalId
from fixbackend.permissions.role_repository import RoleRepository
from fixbackend.utils import uid
from fixbackend.workspaces.models import Workspace
from fixbackend.permissions.models import Roles
from fixbackend.auth.user_repository import UserRepository
from fixbackend.workspaces.repository import WorkspaceRepository


@pytest.fixture
async def client(
    user: User, fast_api: FastAPI, user_repository: UserRepository
) -> AsyncIterator[AsyncClient]:  # noqa: F811

    async def fetch_user() -> User | None:
        return await user_repository.get(user.id)

    fast_api.dependency_overrides[get_current_active_verified_user] = fetch_user
    fast_api.dependency_overrides[maybe_current_active_verified_user] = fetch_user

    async with AsyncClient(app=fast_api, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_list_organizations(client: AsyncClient, workspace: Workspace) -> None:
    response = await client.get("/api/workspaces/")
    assert response.json()[0] is not None
    assert response.json()[0].get("id") == str(workspace.id)
    assert response.json()[0].get("user_permissions") == 8191
    assert response.json()[0].get("tier") == ProductTier.Trial.value
    assert response.json()[0].get("move_to_free_acknowledged_at") is None


@pytest.mark.asyncio
async def test_cloudformation_link(client: AsyncClient, default_config: Config, workspace: Workspace) -> None:
    response = await client.get(f"/api/workspaces/{workspace.id}/cf_url")
    url = response.json()
    assert str(default_config.cf_template_url) in url
    assert str(workspace.id) in url
    assert str(workspace.external_id) in url


@pytest.mark.asyncio
async def test_external_id(client: AsyncClient, workspace: Workspace) -> None:
    response = await client.get(f"/api/workspaces/{workspace.id}/external_id")
    assert response.json().get("external_id") == str(workspace.external_id)


@pytest.mark.asyncio
async def test_cloudformation_template_url(client: AsyncClient, default_config: Config, workspace: Workspace) -> None:
    response = await client.get(f"/api/workspaces/{workspace.id}/cf_template")
    assert response.json() == str(default_config.cf_template_url)


@pytest.mark.asyncio
async def test_get_workspace_settings(
    client: AsyncClient, workspace: Workspace, user: User, role_repository: RoleRepository
) -> None:

    await role_repository.add_roles(user.id, workspace.id, Roles.workspace_admin)

    response = await client.get(f"/api/workspaces/{workspace.id}/settings")
    assert response.json().get("id") == str(workspace.id)
    assert response.json().get("slug") == workspace.slug
    assert response.json().get("name") == workspace.name
    assert response.json().get("external_id") == str(workspace.external_id)


@pytest.mark.asyncio
async def test_update_workspace_settings(
    client: AsyncClient, workspace: Workspace, user: User, role_repository: RoleRepository
) -> None:

    await role_repository.add_roles(user.id, workspace.id, Roles.workspace_admin)

    payload = {"name": "new name", "generate_new_external_id": True}
    response = await client.patch(f"/api/workspaces/{workspace.id}/settings", json=payload)
    assert response.json().get("id") == str(workspace.id)
    assert response.json().get("slug") == workspace.slug
    assert response.json().get("name") == "new name"
    assert response.json().get("external_id") != str(workspace.external_id)


@pytest.mark.asyncio
async def test_list_workspace_users(
    client: AsyncClient, workspace: Workspace, user: User, role_repository: RoleRepository
) -> None:

    response = await client.get(f"/api/workspaces/{workspace.id}/users/")
    user_json = response.json()[0]
    assert user_json.get("id") == str(user.id)
    assert user_json.get("email") == user.email
    assert user_json.get("name") == user.email
    assert user_json.get("roles") == {
        "member": False,
        "admin": False,
        "owner": True,
        "billing_admin": False,
    }

    await role_repository.add_roles(user.id, workspace.id, Roles.workspace_admin)
    response = await client.get(f"/api/workspaces/{workspace.id}/users/")
    user_json = response.json()[0]
    assert user_json.get("roles") == {
        "member": False,
        "admin": True,
        "owner": True,
        "billing_admin": False,
    }


@pytest.mark.asyncio
async def test_list_workspace_roles(
    client: AsyncClient, workspace: Workspace, user: User, role_repository: RoleRepository
) -> None:

    response = await client.get(f"/api/workspaces/{workspace.id}/roles/")
    user_json = response.json()
    assert set(user_json.get("roles")) == {"member", "admin", "owner", "billing_admin"}


@pytest.mark.skip("TODO: fix")
async def test_workspace_trial_period() -> None:
    workspace = Workspace(
        WorkspaceId(uid()),
        "slug",
        "name",
        ExternalId(uid()),
        UserId(uid()),
        [],
        ProductTier.Trial,
        utc(),
        utc(),
    )
    # todo: test for 14 days strictly once we disable rolling trial period duration
    trial_left = workspace.trial_end_days()
    assert trial_left is not None
    assert trial_left >= 14
    # todo: ucomment this once we disable rolling trial period duration
    # assert evolve(workspace, created_at=utc() - timedelta(days=15)).trial_end_days() == 0
    # assert evolve(workspace, created_at=utc() - timedelta(days=10)).trial_end_days() == 4


@pytest.mark.asyncio
async def test_ack_free_move(
    client: AsyncClient, workspace: Workspace, workspace_repository: WorkspaceRepository
) -> None:
    await workspace_repository.update_product_tier(workspace.id, ProductTier.Free)
    response = await client.get("/api/workspaces/")
    assert response.json()[0] is not None
    assert response.json()[0].get("id") == str(workspace.id)
    assert response.json()[0].get("user_permissions") == 8191
    assert response.json()[0].get("tier") == ProductTier.Free.value
    assert response.json()[0].get("move_to_free_acknowledged_at") is None
    update_resp = await client.post(f"/api/workspaces/{workspace.id}/ack_move_to_free")
    assert update_resp.status_code == 200
    response = await client.get("/api/workspaces/")
    assert response.json()[0].get("move_to_free_acknowledged_at") is not None
