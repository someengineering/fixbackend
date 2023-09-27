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
from typing import Optional, Dict, AsyncIterator, Any, List, cast, Union

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
        self, access: GraphDatabaseAccess, command: str, *, env: Optional[Dict[str, str]] = None
    ) -> AsyncIterator[Json]:
        headers = self.__headers(access, accept="application/ndjson", content_type="text/plain")
        response = await self.client.post(
            self.inventory_url + "/cli/execute", content=command, params=env, headers=headers
        )
        if response.is_error:
            raise Exception(f"Inventory error: {response.status_code} {response.text}")
        content_type: str = response.headers.get("content-type", "")
        assert content_type in ("application/x-ndjson", "application/json"), f"ndjson expected, but got {content_type}"
        async for line in response.aiter_lines():
            yield json.loads(line)

    async def search_list(
        self,
        access: GraphDatabaseAccess,
        query: str,
        *,
        graph: str = "resoto",
        section: str = "reported",
    ) -> AsyncIterator[Json]:
        headers = self.__headers(access, accept="application/ndjson", content_type="text/plain")
        params = {"section": section}
        response = await self.client.post(
            self.inventory_url + f"/graph/{graph}/search/list", content=query, params=params, headers=headers
        )
        if response.is_error:
            raise Exception(f"Inventory error: {response.status_code} {response.text}")
        async for line in response.aiter_lines():
            yield json.loads(line)

    async def aggregate(
        self,
        access: GraphDatabaseAccess,
        query: str,
        *,
        graph: str = "resoto",
        section: str = "reported",
    ) -> AsyncIterator[Json]:
        headers = self.__headers(access, accept="application/ndjson", content_type="text/plain")
        params = {"section": section}
        response = await self.client.post(
            self.inventory_url + f"/graph/{graph}/search/aggregate", content=query, params=params, headers=headers
        )
        if response.is_error:
            raise Exception(f"Inventory error: {response.status_code} {response.text}")
        async for line in response.aiter_lines():
            yield json.loads(line)

    async def benchmarks(
        self,
        access: GraphDatabaseAccess,
        *,
        benchmarks: Optional[List[str]] = None,
        short: Optional[bool] = None,
        with_checks: Optional[bool] = None,
    ) -> List[Json]:
        params: Dict[str, Union[str, bool]] = {}
        if benchmarks:
            params["benchmarks"] = ",".join(benchmarks)
        if short is not None:
            params["short"] = short
        if with_checks is not None:
            params["with_checks"] = with_checks
        headers = self.__headers(access)
        response = await self.client.get(self.inventory_url + "/report/benchmarks", params=params, headers=headers)
        if response.is_error:
            raise Exception(f"Inventory error: {response.status_code} {response.text}")
        return cast(List[Json], response.json())

    def __headers(
        self,
        access: GraphDatabaseAccess,
        accept: Optional[str] = "application/json",
        content_type: Optional[str] = None,
    ) -> Dict[str, str]:
        result = {
            "FixGraphDbServer": access.server,
            "FixGraphDbDatabase": access.database,
            "FixGraphDbUsername": access.username,
            "FixGraphDbPassword": access.password,
        }
        if accept:
            result["Accept"] = accept
        if content_type:
            result["Content-Type"] = content_type
        return result
