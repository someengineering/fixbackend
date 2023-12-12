from fastapi import APIRouter, WebSocket, Depends
from fixbackend.config import Config
from fixbackend.workspaces.dependencies import get_optional_user_workspace, WorkspaceError
from fixbackend.workspaces.models import Workspace
from fixbackend.events.websocket_event_handler import WebsockedtEventHandlerDependency
from typing import Annotated, Union


def websocket_router(config: Config) -> APIRouter:
    router = APIRouter()

    @router.websocket("/{workspace_id}/events")
    async def events(
        websocket: WebSocket,
        workspace: Annotated[Union[Workspace, WorkspaceError], Depends(get_optional_user_workspace)],
        event_handler: WebsockedtEventHandlerDependency,
    ) -> None:
        await websocket.accept()
        # check if the user is authorized to listen to this tenant
        if isinstance(workspace, str):
            # 4000 - 4999 are reserved for application errors.
            # We use 4401 for unauthorized access.
            await websocket.close(code=4401, reason=workspace)
            return

        await event_handler.handle_websocket(workspace.id, websocket)

    return router
