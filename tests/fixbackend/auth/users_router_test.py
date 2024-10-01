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
from fastapi import FastAPI
from httpx import AsyncClient

from fixbackend.auth.depedencies import get_current_active_verified_user
from fixbackend.auth.models import User
from fixbackend.config import Config
from fixbackend.config import config as get_config
from fixbackend.dependencies import fix_dependencies, FixDependencies


@pytest.fixture
async def client(
    default_config: Config, user: User, fast_api: FastAPI, fix_deps: FixDependencies
) -> AsyncIterator[AsyncClient]:  # noqa: F811
    # app.dependency_overrides[get_async_session] = lambda: session
    fast_api.dependency_overrides[get_config] = lambda: default_config
    # app.dependency_overrides[get_cloud_account_service] = lambda: cloud_account_service
    fast_api.dependency_overrides[get_current_active_verified_user] = lambda: user
    fast_api.dependency_overrides[fix_dependencies] = lambda: fix_deps

    async with AsyncClient(app=fast_api, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_user_notification_settings(client: AsyncClient) -> None:
    response = await client.get("/api/users/me/settings/notifications")
    assert response.status_code == 200
    assert response.json() == {"inactivity_reminder": True, "weekly_report": True, "tutorial": True, "marketing": True}

    response = await client.put("/api/users/me/settings/notifications", json={"weekly_report": False})
    assert response.status_code == 200
    assert response.json() == {"inactivity_reminder": True, "weekly_report": False, "tutorial": True, "marketing": True}
