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
from typing import Optional, Dict, AsyncIterator, List, cast, Union, Literal, Tuple, Set

from fixcloudutils.service import Service
from fixcloudutils.types import Json, JsonElement
from httpx import AsyncClient, Response

from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.ids import CloudAccountId, NodeId


class GraphDatabaseException(Exception):
    pass


class GraphDatabaseNotAvailable(GraphDatabaseException):
    pass


class GraphDatabaseForbidden(GraphDatabaseException):
    pass


class InventoryClient(Service):
    def __init__(self, inventory_url: str, client: AsyncClient) -> None:
        self.inventory_url = inventory_url
        self.client = client

    async def execute_single(
        self, access: GraphDatabaseAccess, command: str, *, env: Optional[Dict[str, str]] = None
    ) -> AsyncIterator[JsonElement]:
        headers = self.__headers(access, accept="application/ndjson", content_type="text/plain")
        response = await self.client.post(
            self.inventory_url + "/cli/execute", content=command, params=env, headers=headers
        )
        self.__raise_on_error(response, ("application/x-ndjson", "application/ndjson"))
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
        self.__raise_on_error(response, ("application/x-ndjson", "application/ndjson"))
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
        self.__raise_on_error(response, ("application/x-ndjson", "application/ndjson"))
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
        self.__raise_on_error(response, ("application/json",))
        return cast(List[Json], response.json())

    async def issues(
        self,
        access: GraphDatabaseAccess,
        *,
        provider: Optional[str] = None,
        service: Optional[str] = None,
        category: Optional[str] = None,
        kind: Optional[str] = None,
        check_ids: Optional[List[str]] = None,
    ) -> List[Json]:
        params: Dict[str, Union[str, bool]] = {}
        if provider is not None:
            params["provider"] = provider
        if service is not None:
            params["service"] = service
        if category is not None:
            params["category"] = category
        if kind is not None:
            params["kind"] = kind
        if check_ids:
            params["id"] = ",".join(check_ids)
        headers = self.__headers(access)
        response = await self.client.get(self.inventory_url + "/report/checks", params=params, headers=headers)
        self.__raise_on_error(response, ("application/json",))
        return cast(List[Json], response.json())

    async def delete_account(
        self,
        access: GraphDatabaseAccess,
        *,
        cloud: str,
        account_id: CloudAccountId,
        graph: str = "resoto",
    ) -> None:
        query = f'is(account) and id=={account_id} and /ancestors.cloud.reported.name=="{cloud}" limit 1'
        headers = self.__headers(access)
        async for node in self.search_list(access, query):
            node_id = node["id"]
            response = await self.client.delete(self.inventory_url + f"/graph/{graph}/node/{node_id}", headers=headers)
            self.__raise_on_error(response)

    async def possible_values(
        self,
        access: GraphDatabaseAccess,
        *,
        query: str,
        prop_or_predicate: str,
        detail: Literal["attributes", "values"] = "values",
        limit: int = 10,
        skip: int = 0,
        count: bool = False,
        graph: str = "resoto",
        section: str = "reported",
    ) -> AsyncIterator[JsonElement]:
        headers = self.__headers(access, accept="application/ndjson", content_type="text/plain")
        params = {
            "section": section,
            "prop": prop_or_predicate,
            "limit": str(limit),
            "skip": str(skip),
            "count": json.dumps(count),
        }
        response = await self.client.post(
            self.inventory_url + f"/graph/{graph}/property/{detail}", content=query, params=params, headers=headers
        )
        self.__raise_on_error(response, ("application/x-ndjson", "application/ndjson"))
        async for line in response.aiter_lines():
            yield json.loads(line)

    async def resource(self, access: GraphDatabaseAccess, *, id: NodeId, graph: str = "resoto") -> Optional[Json]:
        headers = self.__headers(access, accept="application/json", content_type="text/plain")
        response = await self.client.get(self.inventory_url + f"/graph/{graph}/node/{id}", headers=headers)
        self.__raise_on_error(response, ("application/json",), allowed_error_codes={404})
        return None if response.status_code == 404 else response.json()

    async def model(
        self,
        access: GraphDatabaseAccess,
        *,
        result_format: Optional[str] = None,
        kind: Optional[List[str]] = None,
        kind_filter: Optional[List[str]] = None,
        with_bases: bool = False,
        with_property_kinds: bool = False,
        flat: bool = False,
        graph: str = "resoto",
    ) -> List[Json]:
        headers = self.__headers(access, accept="application/ndjson", content_type="text/plain")
        params = {
            "format": result_format,
            "kind": ",".join(kind) if kind else None,
            "filter": ",".join(kind_filter) if kind_filter else None,
            "with_bases": json.dumps(with_bases),
            "with_property_kinds": json.dumps(with_property_kinds),
            "flat": json.dumps(flat),
        }
        response = await self.client.get(self.inventory_url + f"/graph/{graph}/model", params=params, headers=headers)
        self.__raise_on_error(response, ("application/json",))
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

    def __raise_on_error(
        self,
        response: Response,
        expected_media_types: Optional[Tuple[str, ...]] = None,
        allowed_error_codes: Optional[Set[int]] = None,
    ) -> None:
        if response.is_error and (allowed_error_codes is None or response.status_code in allowed_error_codes):
            msg = f"Inventory error: {response.status_code} {response.text}"
            if response.status_code == 401:
                raise GraphDatabaseForbidden(msg)
            elif response.status_code == 400 and "[HTTP 401][ERR 11]" in response.text:
                raise GraphDatabaseNotAvailable(msg)
            else:
                raise GraphDatabaseException(msg)
        if expected_media_types is not None:
            media_type, *params = response.headers.get("content-type", "").split(";")
            assert (
                media_type in expected_media_types
            ), f"Expected content type {expected_media_types}, but got {media_type}"
