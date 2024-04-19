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
from typing import Any, AsyncIterator, Dict

import pytest
from fastapi import WebSocket, FastAPI
from fixcloudutils.util import utc
from httpx import AsyncClient
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.config import Config
from fixbackend.config import config as get_config
from fixbackend.db import get_async_session
from fixbackend.events.websocket_event_handler import WebsocketEventHandler, get_websocket_event_handler
from fixbackend.ids import ExternalId, UserId, WorkspaceId, ProductTier
from fixbackend.utils import uid
from fixbackend.workspaces.dependencies import get_optional_user_workspace
from fixbackend.workspaces.models import Workspace

workspace_id = WorkspaceId(uuid.uuid4())
workspace = Workspace(
    workspace_id, "foo", "foo", ExternalId(uuid.uuid4()), UserId(uid()), [], ProductTier.Free, utc(), utc()
)


class WebsocketHandlerMock(WebsocketEventHandler):
    def __init__(
        self,
    ) -> None:
        self.tenants: Dict[WorkspaceId, WebSocket] = {}

    async def send_to_workspace(self, workspace_id: WorkspaceId, message: Any) -> None:
        websocket = self.tenants[workspace_id]
        await websocket.send_json(message)

    async def handle_websocket(self, workspace_id: WorkspaceId, websocket: WebSocket) -> None:
        self.tenants[workspace_id] = websocket
        try:
            while True:
                await websocket.receive_json()
        except Exception:
            pass


event_service = WebsocketHandlerMock()


@pytest.fixture
async def websocket_client(
    session: AsyncSession, default_config: Config, fast_api: FastAPI
) -> AsyncIterator[AsyncClient]:  # noqa: F811
    fast_api.dependency_overrides[get_async_session] = lambda: session
    fast_api.dependency_overrides[get_config] = lambda: default_config
    fast_api.dependency_overrides[get_optional_user_workspace] = lambda: workspace
    fast_api.dependency_overrides[get_websocket_event_handler] = lambda: event_service

    async with AsyncClient(base_url="http://test", transport=ASGIWebSocketTransport(fast_api)) as ac:
        yield ac


@pytest.mark.asyncio
async def test_websocket(websocket_client: AsyncClient) -> None:
    async with aconnect_ws(f"/api/workspaces/{workspace_id}/events", websocket_client) as ws:
        await event_service.send_to_workspace(workspace_id, {"type": "foo"})
        message = await ws.receive_json()
        assert message["type"] == "foo"
