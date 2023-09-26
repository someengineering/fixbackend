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
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
import json
from typing import Optional, Dict, AsyncIterator, Any

from fixcloudutils.service import Service
from fixcloudutils.types import Json
from httpx import AsyncClient

from fixbackend.graph_db.models import GraphDatabaseAccess


class InventoryClient(Service):
    def __init__(self, inventory_url: str, client: Optional[AsyncClient] = None) -> None:
        self.inventory_url = inventory_url
        self.client = client or AsyncClient()

    async def start(self) -> Any:
        await self.client.__aenter__()

    async def stop(self) -> None:
        await self.client.__aexit__(None, None, None)

    async def execute_single(
        self, access: GraphDatabaseAccess, command: str, env: Optional[Dict[str, str]] = None
    ) -> AsyncIterator[Json]:
        response = await self.client.post(
            self.inventory_url + "/cli/execute",
            content=command,
            params=env,
            headers={
                "Content-Type": "text/plain",
                "Accept": "application/ndjson",
                "FixGraphDbServer": access.server,
                "FixGraphDbDatabase": access.database,
                "FixGraphDbUsername": access.username,
                "FixGraphDbPassword": access.password,
            },
        )
        if response.is_error:
            raise Exception(f"Inventory error: {response.status_code} {response.text}")
        content_type: str = response.headers.get("content-type", "")
        assert content_type in ("application/x-ndjson", "application/json"), f"ndjson expected, but got {content_type}"
        async for line in response.aiter_lines():
            yield json.loads(line)
