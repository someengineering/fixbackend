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
import logging
from typing import List, Optional, Annotated

from fastapi import APIRouter, Query, Request, Depends, Form, Path
from fastapi.responses import StreamingResponse, JSONResponse
from fixcloudutils.types import Json

from fixbackend.dependencies import FixDependencies, FixDependency
from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.ids import NodeId
from fixbackend.inventory.schemas import ReportSummary, SearchStartData
from fixbackend.streaming_response import streaming_response
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
    router = APIRouter()

    @router.get("/{workspace_id}/inventory/report/{benchmark_name}")
    async def report(
        benchmark_name: str,
        graph_db: CurrentGraphDbDependency,
        request: Request,
        accounts: Optional[List[str]] = Query(None, description="Comma separated list of accounts."),
        severity: Optional[str] = Query(None, enum=["info", "low", "medium", "high", "critical"]),
        only_failing: bool = Query(False),
    ) -> StreamingResponse:
        log.info(f"Show benchmark {benchmark_name} for tenant {graph_db.workspace_id}")
        result = await fix.inventory.benchmark(
            graph_db, benchmark_name, accounts=accounts, severity=severity, only_failing=only_failing
        )
        return streaming_response(request.headers.get("accept", "application/json"), result)

    @router.get("/{workspace_id}/inventory/report-summary")
    async def summary(graph_db: CurrentGraphDbDependency) -> ReportSummary:
        return await fix.inventory.summary(graph_db)

    @router.get("/{workspace_id}/inventory/search/start")
    async def search_start(graph_db: CurrentGraphDbDependency) -> SearchStartData:
        return await fix.inventory.search_start_data(graph_db)

    @router.get("/{workspace_id}/inventory/model")
    async def model(
        graph_db: CurrentGraphDbDependency,
        kind: List[str] = Query(description="Kinds to return."),
        with_bases: bool = Query(default=False, description="Include base kinds."),
        with_property_kinds: bool = Query(default=False, description="Include property kinds."),
        flat: bool = Query(default=True, description="Return a flat list of kinds."),
    ) -> List[Json]:
        return await fix.inventory.client.model(
            graph_db,
            result_format="simple",
            kind=kind,
            with_bases=with_bases,
            with_property_kinds=with_property_kinds,
            flat=flat,
        )

    @router.post("/{workspace_id}/inventory/property/attributes")
    async def property_attributes(
        graph_db: CurrentGraphDbDependency,
        request: Request,
        query: str = Form(),
        prop: str = Form(),
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=10, ge=0, le=50),
        count: bool = Query(default=False),
    ) -> StreamingResponse:
        result = fix.inventory.client.possible_values(
            graph_db, query=query, prop_or_predicate=prop, detail="attributes", skip=skip, limit=limit, count=count
        )
        return streaming_response(request.headers.get("accept", "application/json"), result)

    @router.post("/{workspace_id}/inventory/property/values")
    async def property_values(
        graph_db: CurrentGraphDbDependency,
        request: Request,
        query: str = Form(),
        prop: str = Form(),
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=10, ge=0, le=50),
        count: bool = Query(default=False),
    ) -> StreamingResponse:
        result = fix.inventory.client.possible_values(
            graph_db, query=query, prop_or_predicate=prop, detail="values", skip=skip, limit=limit, count=count
        )
        return streaming_response(request.headers.get("accept", "application/json"), result)

    @router.post("/{workspace_id}/inventory/property/path/complete")
    async def complete_property_path(
        graph_db: CurrentGraphDbDependency,
        prop: Optional[str] = Form(None, description="Current property part."),
        path: Optional[str] = Form(None, description="Existing property path."),
        allowed_kinds: Optional[List[str]] = Form(None, description="List of all allowed kinds."),
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=10, ge=0, le=50),
    ) -> JSONResponse:
        count, result = await fix.inventory.client.complete_property_path(
            access=graph_db, path=path, prop=prop, allowed_kinds=allowed_kinds, skip=skip, limit=limit
        )
        return JSONResponse(result, headers={"Total-Count": str(count)})

    @router.post("/{workspace_id}/inventory/search/table")
    async def search_list(
        graph_db: CurrentGraphDbDependency, request: Request, query: str = Form()
    ) -> StreamingResponse:
        search_result = await fix.inventory.search_table(graph_db, query)
        return streaming_response(request.headers.get("accept", "application/json"), search_result)

    @router.post("/{workspace_id}/inventory/node/{node_id}")
    async def node(graph_db: CurrentGraphDbDependency, node_id: NodeId = Path()) -> Json:
        return await fix.inventory.resource(graph_db, node_id)

    return router
