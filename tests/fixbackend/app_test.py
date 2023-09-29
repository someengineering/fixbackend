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
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.app import fast_api_app
from fixbackend.config import Config
from fixbackend.config import config as get_config
from fixbackend.db import get_async_session


@pytest.fixture
async def client(session: AsyncSession, default_config: Config) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app = fast_api_app(default_config)

    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_config] = lambda: default_config

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_openapi_generation(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
