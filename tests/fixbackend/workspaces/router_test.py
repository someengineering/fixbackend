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
from typing import AsyncIterator, Optional, Sequence
from attrs import evolve

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.app import fast_api_app
from fixbackend.auth.depedencies import get_current_active_verified_user
from fixbackend.workspaces.dependencies import get_user_workspace
from fixbackend.auth.models import User
from fixbackend.config import Config
from fixbackend.config import config as get_config
from fixbackend.db import get_async_session
from fixbackend.ids import ExternalId, UserId, WorkspaceId, SecurityTier
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepositoryImpl, get_workspace_repository

org_id = WorkspaceId(uuid.uuid4())
external_id = ExternalId(uuid.uuid4())
user_id = UserId(uuid.uuid4())
user = User(
    id=user_id,
    email="foo@example.com",
    hashed_password="passord",
    is_verified=True,
    is_active=True,
    is_superuser=False,
    oauth_accounts=[],
)
workspace = Workspace(
    id=org_id,
    name="org name",
    slug="org-slug",
    external_id=external_id,
    owners=[user.id],
    members=[],
    security_tier=SecurityTier.Free,
)


class WorkspaceRepositoryMock(WorkspaceRepositoryImpl):
    def __init__(self) -> None:
        pass

    async def get_workspace(
        self, workspace_id: WorkspaceId, *, session: Optional[AsyncSession] = None
    ) -> Workspace | None:
        return workspace

    async def list_workspaces(self, owner_id: UserId) -> Sequence[Workspace]:
        return [workspace]

    async def update_workspace(self, workspace_id: WorkspaceId, name: str, generate_external_id: bool) -> Workspace:
        if generate_external_id:
            new_external_id = ExternalId(uuid.uuid4())
        else:
            new_external_id = workspace.external_id
        return evolve(workspace, name=name, external_id=new_external_id)

    async def update_security_tier(self, workspace_id: WorkspaceId, security_tier: SecurityTier) -> Workspace:
        return evolve(workspace, security_tier=security_tier)


@pytest.fixture
async def client(session: AsyncSession, default_config: Config) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app = fast_api_app(default_config)

    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_current_active_verified_user] = lambda: user
    app.dependency_overrides[get_config] = lambda: default_config
    app.dependency_overrides[get_workspace_repository] = lambda: WorkspaceRepositoryMock()
    app.dependency_overrides[get_user_workspace] = lambda: workspace

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_list_organizations(client: AsyncClient) -> None:
    response = await client.get("/api/workspaces/")
    assert response.json()[0] is not None


@pytest.mark.asyncio
async def test_cloudformation_link(client: AsyncClient, default_config: Config) -> None:
    response = await client.get(f"/api/workspaces/{org_id}/cf_url")
    url = response.json()
    assert str(default_config.cf_template_url) in url
    assert str(org_id) in url
    assert str(external_id) in url


@pytest.mark.asyncio
async def test_external_id(client: AsyncClient) -> None:
    # organization is created by default
    response = await client.get(f"/api/workspaces/{org_id}/external_id")
    assert response.json().get("external_id") == str(external_id)


@pytest.mark.asyncio
async def test_cloudformation_template_url(client: AsyncClient, default_config: Config) -> None:
    response = await client.get(f"/api/workspaces/{org_id}/cf_template")
    assert response.json() == str(default_config.cf_template_url)


@pytest.mark.asyncio
async def test_get_workspace_settings(client: AsyncClient, default_config: Config) -> None:
    response = await client.get(f"/api/workspaces/{org_id}/settings")
    assert response.json().get("id") == str(org_id)
    assert response.json().get("slug") == workspace.slug
    assert response.json().get("name") == workspace.name
    assert response.json().get("external_id") == str(external_id)


@pytest.mark.asyncio
async def test_update_workspace_settings(client: AsyncClient, default_config: Config) -> None:
    payload = {"name": "new name", "generate_new_external_id": True}
    response = await client.patch(f"/api/workspaces/{org_id}/settings", json=payload)
    assert response.json().get("id") == str(org_id)
    assert response.json().get("slug") == workspace.slug
    assert response.json().get("name") == "new name"
    assert response.json().get("external_id") != str(external_id)


@pytest.mark.asyncio
async def test_billing(client: AsyncClient, default_config: Config) -> None:
    response = await client.get(f"/api/workspaces/{org_id}/billing")
    assert response.json().get("payment_method") == "aws_marketplace"
    assert response.json().get("security_tier") == "free"

    update_response = await client.put(
        f"/api/workspaces/{org_id}/billing", json={"payment_method": "aws_marketplace", "security_tier": "foundational"}
    )

    assert update_response.json().get("payment_method") == "aws_marketplace"
    assert update_response.json().get("security_tier") == "foundational"
