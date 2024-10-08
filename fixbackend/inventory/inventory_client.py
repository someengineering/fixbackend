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
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import (
    Optional,
    Dict,
    AsyncIterator,
    List,
    cast,
    Union,
    Literal,
    Tuple,
    Set,
    TypeVar,
    Generic,
    Callable,
    Any,
    AsyncGenerator,
    AsyncContextManager,
)

from fixcloudutils.service import Service
from fixcloudutils.types import Json, JsonElement
from fixcloudutils.util import utc_str
from httpx import AsyncClient, Response, ReadTimeout, ConnectError
from httpx._types import QueryParamTypes

from fixbackend.errors import ClientError
from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.ids import CloudAccountId, NodeId, SecurityCheckId
from fixbackend.inventory.inventory_schemas import CompletePathRequest, HistoryChange

T = TypeVar("T")
ContextHeaders = {"Total-Count", "Result-Count"}
MediaTypeText = "text/plain"
MediaTypeJson = "application/json"
MediaTypeNdJson = "application/ndjson"
ExpectMediaTypeNdJson = {"application/x-ndjson", MediaTypeNdJson}
DefaultGraph = "fix"
DefaultSection = "reported"
log = logging.getLogger(__name__)


class InventoryException(ClientError):
    def __init__(self, status: int, message: str, *args: Any) -> None:
        super().__init__(message, *args)
        self.status = status


class GraphDatabaseNotAvailable(InventoryException):
    pass


class NoSuchGraph(InventoryException):
    pass


class GraphDatabaseForbidden(InventoryException):
    pass


class InventoryRequestTookTooLong(InventoryException):
    pass


class AsyncIteratorWithContext(Generic[T]):
    def __init__(self, response: Response, fn: Optional[Callable[[str], T]] = None) -> None:
        self.response = response
        self.fn = fn or json.loads
        self.it = response.aiter_lines()
        self.context: Dict[str, str] = {k: response.headers[k] for k in ContextHeaders if k in response.headers}

    def __aiter__(self) -> AsyncIterator[T]:
        return self

    async def __anext__(self) -> T:
        line = await self.it.__anext__()
        return self.fn(line)


class InventoryClient(Service):
    def __init__(self, inventory_url: str, client: AsyncClient) -> None:
        self.inventory_url = inventory_url
        self.client = client

    async def _check_response(
        self,
        response: Response,
        expected_media_types: Optional[Union[str, Set[str]]],
        allowed_error_codes: Optional[Set[int]],
    ) -> None:
        if response.is_error and (allowed_error_codes is None or response.status_code in allowed_error_codes):
            await response.aread()  # make sure the content is read
            if response.status_code == 401:
                raise GraphDatabaseForbidden(401, response.text)
            elif response.status_code == 400 and "[HTTP 401][ERR 11]" in response.text:
                raise GraphDatabaseNotAvailable(404, response.text)
            elif response.status_code == 404 and "NoSuchGraph" in response.text:
                raise NoSuchGraph(404, response.text)
            else:
                raise InventoryException(response.status_code, response.text)
        if expected_media_types is not None and not response.is_error:
            media_type, *params = response.headers.get("content-type", "").split(";")
            emt = {expected_media_types} if isinstance(expected_media_types, str) else expected_media_types
            assert media_type in emt, f"Expected content type {expected_media_types}, but got {media_type}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[QueryParamTypes] = None,
        headers: Optional[Dict[str, str]] = None,
        content: Optional[str] = None,
        json: Optional[Json] = None,
        expected_media_types: Optional[Union[str, Set[str]]] = None,
        allowed_error_codes: Optional[Set[int]] = None,
        read_content: bool = False,
    ) -> Response:
        try:
            response = await self.client.request(
                method, self.inventory_url + path, params=params, headers=headers, content=content, json=json
            )
            if read_content:
                await response.aread()
        except ConnectError as e:
            log.exception(f"Can not connect to inventory: {e}")
            raise InventoryException(502, f"Can not connect to inventory: {e}") from e
        except ReadTimeout as e:
            log.warning(f"Request took too long: {e}")
            # If the request takes longer than the defined timeout, we define this as client error (4xx)
            raise InventoryRequestTookTooLong(408, f"Request took too long: {e}") from e
        else:
            await self._check_response(response, expected_media_types, allowed_error_codes)
            return response

    @asynccontextmanager
    async def _stream(
        self,
        method: str,
        path: str,
        *,
        params: Optional[QueryParamTypes] = None,
        headers: Optional[Dict[str, str]] = None,
        content: Optional[str] = None,
        json: Optional[Json] = None,
        expected_media_types: Optional[Union[str, Set[str]]] = None,
        allowed_error_codes: Optional[Set[int]] = None,
    ) -> AsyncGenerator[AsyncIteratorWithContext[Json], None]:
        try:
            async with self.client.stream(
                method, self.inventory_url + path, params=params, headers=headers, content=content, json=json
            ) as response:
                await self._check_response(response, expected_media_types, allowed_error_codes)
                yield AsyncIteratorWithContext(response)

        except ConnectError as e:
            log.exception(f"Can not connect to inventory: {e}")
            raise InventoryException(502, f"Can not connect to inventory: {e}") from e
        except ReadTimeout as e:
            log.warning(f"Request took too long: {e}")
            # If the request takes longer than the defined timeout, we define this as client error (4xx)
            raise InventoryRequestTookTooLong(408, f"Request took too long: {e}") from e

    async def create_database(self, access: GraphDatabaseAccess, *, graph: str = DefaultGraph) -> None:
        log.info(f"Create new database for tenant: {access.workspace_id}")
        # Create a new database and an empty graph
        await self._request(
            "POST",
            f"/graph/{graph}",
            read_content=True,
            headers=self.__headers(access, content_type=MediaTypeText, FixGraphDbCreateDatabase="true"),
        )

    def execute_single(
        self, access: GraphDatabaseAccess, command: str, *, env: Optional[Dict[str, str]] = None
    ) -> AsyncContextManager[AsyncIteratorWithContext[JsonElement]]:
        log.info(f"Execute command: {command}")
        return self._stream(  # type: ignore
            "POST",
            "/cli/execute",
            content=command,
            params=env,
            headers=self.__headers(access, accept=MediaTypeNdJson, content_type=MediaTypeText),
            expected_media_types=ExpectMediaTypeNdJson,
        )

    def search(
        self,
        access: GraphDatabaseAccess,
        query: str,
        *,
        graph: str = DefaultGraph,
        section: str = DefaultSection,
        with_edges: bool = False,
    ) -> AsyncContextManager[AsyncIteratorWithContext[Json]]:
        list_or_graph = "graph" if with_edges else "list"
        log.info(f"Search {list_or_graph} with query: {query}")
        return self._stream(
            "POST",
            f"/graph/{graph}/search/{list_or_graph}",
            content=query,
            params={"section": section},
            headers=self.__headers(access, accept=MediaTypeNdJson, content_type=MediaTypeText),
            expected_media_types=ExpectMediaTypeNdJson,
        )

    def search_history(
        self,
        access: GraphDatabaseAccess,
        query: str,
        *,
        before: Optional[datetime] = None,
        after: Optional[datetime] = None,
        change: Optional[List[HistoryChange]] = None,
        graph: str = DefaultGraph,
        section: str = DefaultSection,
    ) -> AsyncContextManager[AsyncIteratorWithContext[Json]]:
        log.info(f"Search list with query: {query}")
        params: Dict[str, str] = {"section": section}
        if before:
            params["before"] = utc_str(before)
        if after:
            params["after"] = utc_str(after)
        if change:
            params["change"] = ",".join(change)
        return self._stream(
            "POST",
            f"/graph/{graph}/search/history/list",
            content=query,
            params=params,
            headers=self.__headers(access, accept=MediaTypeNdJson, content_type=MediaTypeText),
            expected_media_types=ExpectMediaTypeNdJson,
        )

    def history_timeline(
        self,
        access: GraphDatabaseAccess,
        query: str,
        after: datetime,
        before: datetime,
        *,
        granularity: Optional[str] = None,
        change: Optional[List[HistoryChange]] = None,
        graph: str = DefaultGraph,
        section: str = DefaultSection,
    ) -> AsyncContextManager[AsyncIteratorWithContext[Json]]:
        log.info(f"History Timeline {after}-{before}: query:{query}, granularity:{granularity}, change:{change}")
        headers = self.__headers(access, accept=MediaTypeNdJson, content_type=MediaTypeText)
        params: Json = dict(after=utc_str(after), before=utc_str(before), section=section)
        if granularity:
            params["granularity"] = granularity
        if change:
            params["change"] = ",".join(change)
        return self._stream(
            "POST",
            f"/graph/{graph}/search/history/timeline",
            content=query,
            params=params,
            headers=headers,
            expected_media_types=ExpectMediaTypeNdJson,
        )

    def aggregate(
        self,
        access: GraphDatabaseAccess,
        query: str,
        *,
        graph: str = DefaultGraph,
        section: str = DefaultSection,
    ) -> AsyncContextManager[AsyncIteratorWithContext[Json]]:
        log.info(f"Aggregate with query: {query}")
        return self._stream(
            "POST",
            f"/graph/{graph}/search/aggregate",
            content=query,
            params={"section": section},
            headers=self.__headers(access, accept=MediaTypeNdJson, content_type=MediaTypeText),
            expected_media_types=ExpectMediaTypeNdJson,
        )

    async def benchmarks(
        self,
        access: GraphDatabaseAccess,
        *,
        benchmarks: Optional[List[str]] = None,
        short: Optional[bool] = None,
        with_checks: Optional[bool] = None,
        ids_only: Optional[bool] = None,
    ) -> List[Json]:
        log.info(f"Get benchmarks with params: {benchmarks}, {short}, {with_checks}")
        params: Dict[str, Union[str, bool]] = {}
        if benchmarks is not None and len(benchmarks) == 0:
            return []
        if benchmarks:
            params["benchmarks"] = ",".join(benchmarks)
        if short is not None:
            params["short"] = short
        if with_checks is not None:
            params["with_checks"] = with_checks
        if ids_only is not None:
            params["ids_only"] = ids_only
        response = await self._request(
            "GET",
            "/report/benchmarks",
            params=params,
            headers=self.__headers(access),
            expected_media_types=MediaTypeJson,
            read_content=True,
        )
        return cast(List[Json], response.json())

    async def checks(
        self,
        access: GraphDatabaseAccess,
        *,
        provider: Optional[str] = None,
        service: Optional[str] = None,
        category: Optional[str] = None,
        kind: Optional[str] = None,
        check_ids: Optional[List[SecurityCheckId]] = None,
        ids_only: Optional[bool] = None,
    ) -> List[Json]:
        log.info(
            f"Get issues with provider={provider}, service={service}, category={category}, kind={kind}, ids={check_ids}"
        )
        if check_ids is not None and len(check_ids) == 0:
            return []
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
        if ids_only is not None:
            params["ids_only"] = ids_only
        response = await self._request(
            "GET",
            "/report/checks",
            params=params,
            headers=self.__headers(access),
            expected_media_types=MediaTypeJson,
            read_content=True,
        )
        return cast(List[Json], response.json())

    async def delete_account(
        self,
        access: GraphDatabaseAccess,
        *,
        cloud: str,
        account_id: CloudAccountId,
        graph: str = DefaultGraph,
    ) -> None:
        log.info(f"Delete account {account_id} from cloud {cloud}")
        query = f'is(account) and id=={account_id} and /ancestors.cloud.reported.name=="{cloud}" limit 1'
        async with self.search(access, query) as results:
            async for node in results:
                node_id = node["id"]
                await self._request("DELETE", f"/graph/{graph}/node/{node_id}", headers=self.__headers(access))

    async def complete_property_path(
        self,
        access: GraphDatabaseAccess,
        *,
        request: CompletePathRequest,
        graph: str = DefaultGraph,
        section: str = DefaultSection,
    ) -> Tuple[int, Dict[str, str]]:
        log.info(
            f"Complete property path path={request.path}, prop={request.prop}, kinds={len(request.kinds or [])}, "
            f"fuzzy={request.fuzzy}, skip={request.skip}, limit={request.limit}"
        )
        response = await self._request(
            "POST",
            f"/graph/{graph}/property/path/complete",
            json=request.model_dump(),
            headers=self.__headers(access),
            params={"section": section},
            expected_media_types=MediaTypeJson,
            read_content=True,
        )
        count = int(response.headers.get("Total-Count", "0"))
        return count, cast(Dict[str, str], response.json())

    def possible_values(
        self,
        access: GraphDatabaseAccess,
        *,
        query: str,
        prop_or_predicate: str,
        detail: Literal["attributes", "values"] = "values",
        limit: int = 10,
        skip: int = 0,
        count: bool = False,
        graph: str = DefaultGraph,
        section: str = DefaultSection,
    ) -> AsyncContextManager[AsyncIteratorWithContext[JsonElement]]:
        log.info(f"Get possible values with query: {query}, prop_or_predicate: {prop_or_predicate} on detail: {detail}")
        params = {
            "section": section,
            "prop": prop_or_predicate,
            "limit": str(limit),
            "skip": str(skip),
            "count": json.dumps(count),
        }
        return self._stream(  # type: ignore
            "POST",
            f"/graph/{graph}/property/{detail}",
            content=query,
            params=params,
            headers=self.__headers(access, accept=MediaTypeNdJson, content_type=MediaTypeText),
            expected_media_types=ExpectMediaTypeNdJson,
        )

    async def resource(self, access: GraphDatabaseAccess, *, id: NodeId, graph: str = DefaultGraph) -> Optional[Json]:
        log.info(f"Get resource with id: {id}")
        headers = self.__headers(access, accept=MediaTypeJson, content_type=MediaTypeText)
        response = await self._request(
            "GET",
            f"/graph/{graph}/node/{id}",
            headers=headers,
            expected_media_types=MediaTypeJson,
            allowed_error_codes={404},
            read_content=True,
        )
        return None if response.status_code == 404 else response.json()

    async def model(
        self,
        access: GraphDatabaseAccess,
        *,
        result_format: Optional[str] = None,
        flat: bool = False,
        # kind selection options
        with_bases: bool = False,
        with_property_kinds: bool = False,
        kind: Optional[List[str]] = None,
        kind_filter: Optional[List[str]] = None,
        aggregate_roots_only: bool = False,
        # format options
        with_properties: bool = True,
        with_relatives: bool = True,
        with_metadata: Union[bool, List[str]] = True,
        graph: str = DefaultGraph,
    ) -> List[Json]:
        log.info(f"Get model with flat={flat}, with_bases={with_bases}, with_property_kinds={with_property_kinds}")
        params = {
            "format": result_format,
            "kind": ",".join(kind) if kind else None,
            "filter": ",".join(kind_filter) if kind_filter else None,
            "with_bases": json.dumps(with_bases),
            "with_property_kinds": json.dumps(with_property_kinds),
            "flat": json.dumps(flat),
            "aggregate_roots_only": json.dumps(aggregate_roots_only),
            "with_properties": json.dumps(with_properties),
            "with_relatives": json.dumps(with_relatives),
            "with_metadata": ",".join(with_metadata) if isinstance(with_metadata, list) else json.dumps(with_metadata),
        }
        response = await self._request(
            "GET",
            f"/graph/{graph}/model",
            params=params,
            headers=self.__headers(access, accept=MediaTypeJson, content_type=MediaTypeText),
            expected_media_types=MediaTypeJson,
            read_content=True,
        )
        return cast(List[Json], response.json())

    def timeseries(
        self,
        access: GraphDatabaseAccess,
        name: str,
        *,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        group: Optional[Set[str]] = None,
        filter_group: Optional[List[str]] = None,
        granularity: Optional[int | timedelta] = None,
        aggregation: Optional[str] = None,
    ) -> AsyncContextManager[AsyncIteratorWithContext[Json]]:
        log.info(
            f"Get timeseries with name: {name}, start: {start}, end: {end}, "
            f"group: {group}, filter: {filter_group}, granularity: {granularity}"
        )
        headers = self.__headers(access, accept=MediaTypeNdJson, content_type=MediaTypeJson)
        body: Json = {}
        if start:
            body["start"] = utc_str(start)
        if end:
            body["end"] = utc_str(end)
        if group is not None:
            body["group"] = list(group)
        if filter_group is not None:
            body["filter"] = filter_group
        if granularity:
            value = granularity if isinstance(granularity, int) else f"{granularity.total_seconds()}s"
            body["granularity"] = value
        if aggregation:
            body["aggregation"] = aggregation
        return self._stream(
            "POST",
            f"/timeseries/{name}",
            json=body,
            headers=headers,
            expected_media_types=ExpectMediaTypeNdJson,
        )

    async def update_node(
        self,
        access: GraphDatabaseAccess,
        node_id: NodeId,
        patch: Json,
        *,
        graph: str = DefaultGraph,
        section: str = DefaultSection,
        force: bool = False,
    ) -> Json:
        log.info(f"Update node with id: {id}")
        response = await self._request(
            "PATCH",
            f"/graph/{graph}/node/{node_id}",
            json=patch,
            headers=self.__headers(access, accept=MediaTypeJson, content_type=MediaTypeJson),
            params={"section": section, "force": json.dumps(force)},
            expected_media_types=MediaTypeJson,
            read_content=True,
        )
        return cast(Json, response.json())

    async def config(self, access: GraphDatabaseAccess, config_id: str) -> Json:
        response = await self._request(
            "GET",
            f"/config/{config_id}",
            headers=self.__headers(access, accept=MediaTypeJson, content_type=MediaTypeJson),
            expected_media_types=MediaTypeJson,
            read_content=True,
        )
        return response.json()  # type: ignore

    async def update_config(
        self, access: GraphDatabaseAccess, config_id: str, update: Json, *, patch: bool = False
    ) -> Json:
        response = await self._request(
            "PATCH" if patch else "PUT",
            f"/config/{config_id}",
            json=update,
            headers=self.__headers(access, accept=MediaTypeJson, content_type=MediaTypeJson),
            expected_media_types=MediaTypeJson,
            read_content=True,
        )
        return response.json()  # type: ignore

    async def call_json(
        self,
        access: GraphDatabaseAccess,
        method: str,
        path: str,
        *,
        body: Optional[Json] = None,
        params: Optional[Dict[str, str]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        expect_result: bool = True,
    ) -> Json:
        headers = self.__headers(
            access,
            accept=MediaTypeJson if expect_result else None,
            content_type=MediaTypeJson if body else None,
        )
        if extra_headers is not None:
            headers.update(extra_headers)
        response = await self._request(
            method,
            path,
            json=body,
            headers=headers,
            params=params,
            expected_media_types=MediaTypeJson if expect_result else None,
            read_content=expect_result,
        )
        return response.json() if expect_result else None  # type: ignore

    def __headers(
        self,
        access: GraphDatabaseAccess,
        accept: Optional[str] = MediaTypeJson,
        content_type: Optional[str] = None,
        **additional_headers: str,
    ) -> Dict[str, str]:
        result = {
            "FixGraphDbServer": access.server,
            "FixGraphDbDatabase": access.database,
            "FixGraphDbUsername": access.username,
            "FixGraphDbPassword": access.password,
            **additional_headers,
        }
        if accept:
            result["Accept"] = accept
        if content_type:
            result["Content-Type"] = content_type
        return result
