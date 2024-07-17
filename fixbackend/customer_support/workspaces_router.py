#  Copyright (c) 2024. Some Engineering
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

from datetime import timedelta
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fixcloudutils.util import utc

from fixbackend.cloud_accounts.repository import CloudAccountRepositoryImpl
from fixbackend.dependencies import FixDependencies, ServiceNames
from fixbackend.dispatcher.next_run_repository import NextRunRepository
from fixbackend.domain_events.events import WorkspaceCreated
from fixbackend.domain_events.publisher_impl import DomainEventPublisherImpl
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import FixCloudAccountId, WorkspaceId
from fixbackend.workspaces.repository import WorkspaceRepositoryImpl


def workspaces_router(dependencies: FixDependencies, templates: Jinja2Templates) -> APIRouter:

    router = APIRouter()

    workspace_repo = dependencies.service(ServiceNames.workspace_repo, WorkspaceRepositoryImpl)
    cloud_accont_repo = dependencies.service(ServiceNames.cloud_account_repo, CloudAccountRepositoryImpl)
    next_run_repo = dependencies.service(ServiceNames.next_run_repo, NextRunRepository)
    graph_db_access = dependencies.service(ServiceNames.graph_db_access, GraphDatabaseAccessManager)
    domain_event_sender = dependencies.service(ServiceNames.domain_event_sender, DomainEventPublisherImpl)

    @router.get("/{workspace_id}", response_class=HTMLResponse, name="workspace:get")
    async def get_workspace(request: Request, workspace_id: WorkspaceId) -> Response:
        workspace = await workspace_repo.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")

        cloud_accounts = await cloud_accont_repo.list_by_workspace_id(workspace.id)

        next_run = await next_run_repo.get(workspace.id)

        db_access_not_existent = (await graph_db_access.get_database_access(workspace.id)) is None

        context: Dict[str, Any] = {
            "request": request,
            "workspace": workspace,
            "cloud_accounts": cloud_accounts,
            "next_run": next_run,
            "db_access_not_existent": db_access_not_existent,
        }

        if request.headers.get("HX-Request"):
            context["partial"] = True

        headers = {"Vary": "HX-Request"}

        return templates.TemplateResponse(
            request=request, name="workspaces/workspace.html", headers=headers, context=context
        )

    @router.post(
        "/{workspace_id}/create_graph_db_access",
        response_class=HTMLResponse,
        name="workspace:create_graph_db_access",
    )
    async def create_graph_db_access(request: Request, workspace_id: WorkspaceId) -> Response:
        workspace = await workspace_repo.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")

        existing_db_access = await graph_db_access.get_database_access(workspace.id)
        if existing_db_access:
            raise HTTPException(status_code=400, detail="Database access already exists")

        await graph_db_access.create_database_access(workspace.id)
        await domain_event_sender.publish(
            WorkspaceCreated(workspace.id, workspace.name, workspace.slug, workspace.owner_id)
        )

        return Response(status_code=status.HTTP_201_CREATED, content="")

    @router.post(
        "/{workspace_id}/accounts/{cloud_account_id}",
        response_class=HTMLResponse,
        name="workspace:trigger_single_account_collect",
    )
    async def trigger_collect_account(
        request: Request, workspace_id: WorkspaceId, cloud_account_id: FixCloudAccountId
    ) -> Response:
        workspace = await workspace_repo.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")

        cloud_account = await cloud_accont_repo.get(cloud_account_id)
        if not cloud_account:
            raise HTTPException(status_code=404, detail="Cloud account not found")

        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.delete(
        "/{workspace_id}/next_run",
        response_class=HTMLResponse,
        name="workspace:reset_next_run",
    )
    async def reset_next_run(request: Request, workspace_id: WorkspaceId) -> Response:
        workspace = await workspace_repo.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")

        next_run_time = utc().replace(microsecond=0) - timedelta(minutes=5)

        await next_run_repo.update_next_run_at(
            workspace.id,
            next_run_time,
        )
        return Response(status_code=status.HTTP_202_ACCEPTED, content=f"Next run: {next_run_time}")

    return router
