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

from fastapi import APIRouter, Query, Request, Depends
from fastapi.responses import StreamingResponse

from fixbackend.dependencies import FixDependencies, FixDependency
from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.ids import WorkspaceId
from fixbackend.inventory.schemas import ReportSummary
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
        workspace_id: WorkspaceId,
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
    async def summary(workspace_id: WorkspaceId, graph_db: CurrentGraphDbDependency) -> ReportSummary:
        return await fix.inventory.summary(graph_db)

    return router
