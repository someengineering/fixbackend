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
import logging
from datetime import datetime
from typing import Annotated, List, Literal, Optional, AsyncIterator

from fastapi import APIRouter, Body, Depends, Form, Path, Query, Request
from fastapi.responses import JSONResponse, Response
from fixcloudutils.types import Json

from fixbackend.dependencies import FixDependencies, FixDependency, ServiceNames
from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.ids import NodeId
from fixbackend.inventory.inventory_service import InventoryService
from fixbackend.inventory.schemas import (
    CompletePathRequest,
    HistoryChange,
    ReportConfig,
    ReportSummary,
    SearchRequest,
    SearchStartData,
    SearchListGraphRequest,
    UpdateSecurityIgnore,
)
from fixbackend.streaming_response import streaming_response, StreamOnSuccessResponse
from fixbackend.workspaces.dependencies import UserWorkspaceDependency

log = logging.getLogger(__name__)


async def get_current_graph_db(fix: FixDependency, workspace: UserWorkspaceDependency) -> GraphDatabaseAccess:
    access = await fix.graph_database_access.get_database_access(workspace.id)
    if access is None:
        raise AttributeError("No database access found for tenant")
    return access


# This is the dependency that should be used in most parts of the application.
CurrentGraphDbDependency = Annotated[GraphDatabaseAccess, Depends(get_current_graph_db)]


def inventory_router(fix: FixDependencies) -> APIRouter:
    router = APIRouter(prefix="/{workspace_id}/inventory")

    def inventory() -> InventoryService:
        return fix.service(ServiceNames.inventory, InventoryService)

    @router.get("/report/config", tags=["report-management"])
    async def report_config(graph_db: CurrentGraphDbDependency) -> ReportConfig:
        return await inventory().report_config(graph_db)

    @router.put("/report/config", tags=["report-management"])
    async def update_report_config(graph_db: CurrentGraphDbDependency, config: ReportConfig = Body(...)) -> None:
        await inventory().update_report_config(graph_db, config)

    @router.get("/report/info", tags=["report-management"])
    async def report_info(graph_db: CurrentGraphDbDependency) -> Json:
        return await inventory().report_info(graph_db)

    @router.get("/report/benchmark/{benchmark_name}", tags=["report-management"])
    async def get_benchmark(benchmark_name: str, graph_db: CurrentGraphDbDependency) -> Json:
        return await inventory().client.call_json(graph_db, "get", f"/report/benchmark/{benchmark_name}")

    @router.put("/report/benchmark/{benchmark_name}", tags=["report-management"])
    async def put_benchmark(benchmark_name: str, graph_db: CurrentGraphDbDependency, body: Json = Body()) -> Json:
        return await inventory().client.call_json(graph_db, "put", f"/report/benchmark/{benchmark_name}", body=body)

    @router.delete("/report/benchmark/{benchmark_name}", tags=["report-management"])
    async def delete_benchmark(benchmark_name: str, graph_db: CurrentGraphDbDependency) -> Response:
        await inventory().client.call_json(
            graph_db, "delete", f"/report/benchmark/{benchmark_name}", expect_result=False
        )
        return Response(status_code=204)

    @router.get("/report/check/{check_id}", tags=["report-management"])
    async def get_check(check_id: str, graph_db: CurrentGraphDbDependency) -> Json:
        return await inventory().client.call_json(graph_db, "get", f"/report/check/{check_id}")

    @router.put("/report/check/{check_id}", tags=["report-management"])
    async def put_check(check_id: str, graph_db: CurrentGraphDbDependency, body: Json = Body()) -> Json:
        return await inventory().client.call_json(graph_db, "put", f"/report/check/{check_id}", body=body)

    @router.delete("/report/check/{check_id}", tags=["report-management"])
    async def delete_check(check_id: str, graph_db: CurrentGraphDbDependency) -> Response:
        await inventory().client.call_json(graph_db, "delete", f"/report/check/{check_id}", expect_result=False)
        return Response(status_code=204)

    @router.get("/report/benchmark/{benchmark_name}/result", tags=["report"])
    async def report(
        benchmark_name: str,
        graph_db: CurrentGraphDbDependency,
        request: Request,
        accounts: Optional[List[str]] = Query(None, description="Comma separated list of accounts."),
        severity: Optional[str] = Query(None, enum=["info", "low", "medium", "high", "critical"]),
        only_failing: bool = Query(False),
    ) -> StreamOnSuccessResponse:
        log.info(f"Show benchmark {benchmark_name} for tenant {graph_db.workspace_id}")
        fn, media_type = streaming_response(request.headers.get("accept", "application/json"))

        async def stream() -> AsyncIterator[str]:
            async with inventory().benchmark(
                graph_db, benchmark_name, accounts=accounts, severity=severity, only_failing=only_failing
            ) as result:
                async for elem in fn(result):
                    yield elem

        return StreamOnSuccessResponse(stream(), media_type=media_type)

    @router.get("/report-summary", tags=["report"])
    async def summary(graph_db: CurrentGraphDbDependency) -> ReportSummary:
        return await inventory().summary(graph_db)

    @router.get("/model", tags=["inventory"])
    async def model(
        graph_db: CurrentGraphDbDependency,
        kind: List[str] = Query(description="Kinds to return."),
        with_bases: bool = Query(default=False, description="Include base kinds."),
        with_property_kinds: bool = Query(default=False, description="Include property kinds."),
        flat: bool = Query(default=True, description="Return a flat list of kinds."),
    ) -> List[Json]:
        return await inventory().client.model(
            graph_db,
            result_format="simple",
            kind=kind,
            with_bases=with_bases,
            with_property_kinds=with_property_kinds,
            flat=flat,
        )

    @router.get("/search/start", tags=["search"])
    async def search_start(graph_db: CurrentGraphDbDependency) -> SearchStartData:
        return await inventory().search_start_data(graph_db)

    @router.post("/property/attributes", tags=["search"])
    async def property_attributes(
        graph_db: CurrentGraphDbDependency,
        request: Request,
        query: str = Form(),
        prop: str = Form(),
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=10, ge=0, le=50),
        count: bool = Query(default=False),
    ) -> StreamOnSuccessResponse:
        fn, media_type = streaming_response(request.headers.get("accept", "application/json"))

        async def stream() -> AsyncIterator[str]:
            async with inventory().client.possible_values(
                graph_db, query=query, prop_or_predicate=prop, detail="attributes", skip=skip, limit=limit, count=count
            ) as result:
                async for elem in fn(result):
                    yield elem

        return StreamOnSuccessResponse(stream(), media_type=media_type)

    @router.post("/property/values", tags=["search"])
    async def property_values(
        graph_db: CurrentGraphDbDependency,
        request: Request,
        query: str = Form(),
        prop: str = Form(),
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=10, ge=0, le=50),
        count: bool = Query(default=False),
    ) -> StreamOnSuccessResponse:
        fn, media_type = streaming_response(request.headers.get("accept", "application/json"))

        async def stream() -> AsyncIterator[str]:
            async with inventory().client.possible_values(
                graph_db, query=query, prop_or_predicate=prop, detail="values", skip=skip, limit=limit, count=count
            ) as result:
                async for elem in fn(result):
                    yield elem

        return StreamOnSuccessResponse(stream(), media_type=media_type)

    @router.post("/property/path/complete", tags=["search"])
    async def complete_property_path(
        graph_db: CurrentGraphDbDependency,
        body: CompletePathRequest = Body(...),
    ) -> JSONResponse:
        count, result = await inventory().client.complete_property_path(access=graph_db, request=body)
        return JSONResponse(result, headers={"Total-Count": str(count)})

    @router.post(
        "/search",
        description="Search the inventory and return the results as a list of json objects.",
        tags=["search"],
    )
    async def search(
        graph_db: CurrentGraphDbDependency, request: Request, query: SearchListGraphRequest = Body()
    ) -> StreamOnSuccessResponse:
        fn, media_type = streaming_response(request.headers.get("accept", "application/json"))

        async def stream() -> AsyncIterator[str]:
            async with inventory().client.search(graph_db, query.query, with_edges=query.with_edges) as result:
                async for elem in fn(result):
                    yield elem

        return StreamOnSuccessResponse(stream(), media_type=media_type)

    @router.post(
        "/search/table",
        description="Search the inventory and return the results as a table. "
        "Based on the accept header, the result is returned in the expected format.",
        responses={200: {"content": {"text/csv": {}, "application/json": {}}}},
        tags=["search"],
    )
    async def search_table(
        graph_db: CurrentGraphDbDependency, request: Request, query: SearchRequest = Body()
    ) -> StreamOnSuccessResponse:
        accept = request.headers.get("accept", "application/json")
        fn, media_type = streaming_response(accept)
        result_format: Literal["table", "csv"] = "csv" if accept == "text/csv" else "table"
        extra_headers = {}

        async def stream() -> AsyncIterator[str]:
            async with inventory().search_table(graph_db, query, result_format=result_format) as result:
                extra_headers.update(result.context)
                if accept == "text/csv":
                    extra_headers["Content-Disposition"] = 'attachment; filename="inventory.csv"'
                async for elem in fn(result):
                    yield elem

        return StreamOnSuccessResponse(stream(), media_type=media_type, headers=extra_headers)

    @router.get("/node/{node_id}", tags=["search"])
    async def get_node(graph_db: CurrentGraphDbDependency, node_id: NodeId = Path()) -> Json:
        return await inventory().resource(graph_db, node_id)

    @router.patch("/node/{node_id}/security_ignore", tags=["report"])
    async def ignore_security(
        graph_db: CurrentGraphDbDependency,
        node_id: NodeId = Path(),
        ignore: UpdateSecurityIgnore = Body(...),
    ) -> Json:
        return await inventory().client.update_node(
            graph_db, node_id, {"security_ignore": ignore.checks or None}, section="metadata"
        )

    @router.get("/node/{node_id}/neighborhood", tags=["search"])
    async def get_node_neighborhood(
        graph_db: CurrentGraphDbDependency, request: Request, node_id: NodeId = Path()
    ) -> StreamOnSuccessResponse:
        fn, media_type = streaming_response(request.headers.get("accept", "application/json"))

        async def stream() -> AsyncIterator[str]:
            async with inventory().neighborhood(graph_db, node_id) as result:
                async for elem in fn(result):
                    yield elem

        return StreamOnSuccessResponse(stream(), media_type=media_type)

    # deprecated, needs to be removed
    @router.post("/node/{node_id}", tags=["deprecated"])
    async def node(graph_db: CurrentGraphDbDependency, node_id: NodeId = Path()) -> Json:
        return await get_node(graph_db, node_id)

    @router.get("/node/{node_id}/history", tags=["search"])
    async def get_node_history(
        request: Request,
        graph_db: CurrentGraphDbDependency,
        node_id: NodeId = Path(),
        before: Optional[datetime] = Query(default=None),
        after: Optional[datetime] = Query(default=None),
        changes: Optional[List[HistoryChange]] = Query(default=None),
        limit: int = Query(default=20, ge=1),
    ) -> StreamOnSuccessResponse:
        fn, media_type = streaming_response(request.headers.get("accept", "application/json"))

        async def stream() -> AsyncIterator[str]:
            async with inventory().client.search_history(
                graph_db,
                query=f'id("{node_id}") sort /changed_at desc limit {limit}',
                before=before,
                after=after,
                change=changes,
            ) as result:
                async for elem in fn(result):
                    yield elem

        return StreamOnSuccessResponse(stream(), media_type=media_type)

    return router
