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

from fixbackend.app import fast_api_app
from fixbackend.db import get_async_session
from httpx import AsyncClient
from tests.fixbackend.conftest import default_config  # noqa: F401
from tests.fixbackend.organizations.service_test import session, db_engine  # noqa: F401
from fixbackend.config import config as get_config, Config
from sqlalchemy.ext.asyncio import AsyncSession
import pytest
from fixbackend.organizations.dependencies import get_user_tenants
from fixbackend.events.event_service import EventService, get_event_service
import uuid

from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport


tenant_id = uuid.uuid4()

event_service = EventService()


@pytest.fixture
async def websocket_client(session: AsyncSession, default_config: Config) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app = fast_api_app(default_config)

    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_config] = lambda: default_config
    app.dependency_overrides[get_user_tenants] = lambda: [tenant_id]
    app.dependency_overrides[get_event_service] = lambda: event_service

    async with AsyncClient(base_url="http://test", transport=ASGIWebSocketTransport(app)) as ac:
        yield ac


@pytest.mark.asyncio
async def test_websocket(websocket_client: AsyncClient) -> None:
    async with aconnect_ws(f"/ws/events/{tenant_id}", websocket_client) as ws:
        message = await ws.receive_json()
        assert message["type"] == "ping"
        await ws.send_json({"type": "pong"})
        await event_service.send_to_tenant(tenant_id, {"type": "foo"})
        message = await ws.receive_json()
        assert message["type"] == "foo"
