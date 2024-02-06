#  Copyright (c) 2024. Some Engineering
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
from httpx import AsyncClient

from fixbackend.app import fast_api_app
from fixbackend.auth.depedencies import get_current_active_verified_user
from fixbackend.auth.models import User
from fixbackend.config import Config
from fixbackend.config import config as get_config
from fixbackend.workspaces.models import Workspace


@pytest.fixture
async def client(default_config: Config, user: User) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app = fast_api_app(default_config)

    # app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_config] = lambda: default_config
    # app.dependency_overrides[get_cloud_account_service] = lambda: cloud_account_service
    app.dependency_overrides[get_current_active_verified_user] = lambda: user

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_user_notification_settings(client: AsyncClient, workspace: Workspace) -> None:
    response = await client.get(f"/api/workspaces/{workspace.id}/notification/user")
    assert response.status_code == 200
    assert response.json() == {"inactivity_reminder": False, "weekly_report": True}

    response = await client.put(
        f"/api/workspaces/{workspace.id}/notification/user", json={"inactivity_reminder": True, "weekly_report": False}
    )
    assert response.status_code == 200
    assert response.json() == {"inactivity_reminder": True, "weekly_report": False}
