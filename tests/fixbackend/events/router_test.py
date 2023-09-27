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


from typing import Any, AsyncIterator, Dict

from fastapi import WebSocket

from fixbackend.app import fast_api_app
from fixbackend.db import get_async_session
from httpx import AsyncClient
from fixbackend.config import config as get_config, Config
from sqlalchemy.ext.asyncio import AsyncSession
import pytest
from fixbackend.auth.current_user_dependencies import get_user_tenants_ids
from fixbackend.events.websocket_event_handler import (
    WebsocketEventHandler,
    get_websocket_event_handler,
)
import uuid

from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport
from fixbackend.ids import TenantId


tenant_id = TenantId(uuid.uuid4())


class WebsocketHandlerMock(WebsocketEventHandler):
    def __init__(
        self,
    ) -> None:
        self.tenants: Dict[TenantId, WebSocket] = {}

    async def send_to_tenant(self, tenant_id: TenantId, message: Any) -> None:
        websocket = self.tenants[tenant_id]
        await websocket.send_json(message)

    async def handle_websocket(self, tenant_id: TenantId, websocket: WebSocket) -> None:
        self.tenants[tenant_id] = websocket
        try:
            while True:
                await websocket.receive_json()
        except Exception:
            pass


event_service = WebsocketHandlerMock()


@pytest.fixture
async def websocket_client(session: AsyncSession, default_config: Config) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app = fast_api_app(default_config)

    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_config] = lambda: default_config
    app.dependency_overrides[get_user_tenants_ids] = lambda: {tenant_id}
    app.dependency_overrides[get_websocket_event_handler] = lambda: event_service

    async with AsyncClient(base_url="http://test", transport=ASGIWebSocketTransport(app)) as ac:
        yield ac


@pytest.mark.asyncio
async def test_websocket(websocket_client: AsyncClient) -> None:
    async with aconnect_ws(f"/api/organizations/{tenant_id}/events", websocket_client) as ws:
        await event_service.send_to_tenant(tenant_id, {"type": "foo"})
        message = await ws.receive_json()
        assert message["type"] == "foo"
