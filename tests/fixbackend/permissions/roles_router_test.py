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


import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.app import fast_api_app
from fixbackend.auth.depedencies import get_current_active_verified_user
from fixbackend.auth.models import User

from fixbackend.config import Config
from fixbackend.config import config as get_config
from fixbackend.db import get_async_session

from fixbackend.workspaces.dependencies import get_user_workspace
from fixbackend.workspaces.models import Workspace
from fixbackend.permissions.role_repository import RoleRepository, get_role_repository
from typing import AsyncIterator
from fixbackend.auth.user_repository import UserRepository
from fixbackend.workspaces.repository import WorkspaceRepository, get_workspace_repository


@pytest.fixture
async def client(
    session: AsyncSession,
    default_config: Config,
    user: User,
    workspace: Workspace,
    role_repository: RoleRepository,
    workspace_repository: WorkspaceRepository,
) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app = fast_api_app(default_config)

    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_config] = lambda: default_config
    app.dependency_overrides[get_user_workspace] = lambda: workspace
    app.dependency_overrides[get_current_active_verified_user] = lambda: user
    app.dependency_overrides[get_role_repository] = lambda: role_repository
    app.dependency_overrides[get_workspace_repository] = lambda: workspace_repository

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_list_roles(
    client: AsyncClient,
    workspace: Workspace,
    role_repository: RoleRepository,
    user: User,
    user_repository: UserRepository,
    workspace_repository: WorkspaceRepository,
) -> None:

    user_dict = {
        "email": "foo_bar@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }

    new_user = await user_repository.create(user_dict)
    await workspace_repository.add_to_workspace(workspace.id, new_user.id)
    response = await client.get(f"/api/workspaces/{workspace.id}/roles")
    assert response.status_code == 200
    json = response.json()

    assert len(json) == 2
    assert list(filter(lambda x: x["user_id"] == str(user.id), json)) == [
        {
            "user_id": str(user.id),
            "workspace_id": str(workspace.id),
            "member": False,
            "admin": False,
            "owner": True,
            "billing_admin": False,
        }
    ]

    assert list(filter(lambda x: x["user_id"] == str(new_user.id), json)) == [
        {
            "user_id": str(new_user.id),
            "workspace_id": str(workspace.id),
            "member": True,
            "admin": False,
            "owner": False,
            "billing_admin": False,
        },
    ]


@pytest.mark.asyncio
async def test_update_roles(
    client: AsyncClient,
    workspace: Workspace,
    user: User,
) -> None:

    payload = {"user_id": str(user.id), "member": False, "admin": False, "owner": False, "billing_admin": True}

    response = await client.put(f"/api/workspaces/{workspace.id}/roles/{user.id}", json=payload)
    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(user.id),
        "workspace_id": str(workspace.id),
        "member": False,
        "admin": False,
        "owner": False,
        "billing_admin": True,
    }
