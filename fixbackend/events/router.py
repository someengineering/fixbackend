from fastapi import APIRouter, WebSocket, Depends
from fixbackend.config import Config
from fixbackend.workspaces.dependencies import get_optional_user_workspace, WorkspaceError
from fixbackend.workspaces.models import Workspace
from fixbackend.events.websocket_event_handler import WebsockedtEventHandlerDependency
from typing import Annotated, Union
from logging import getLogger


logger = getLogger(__name__)


def websocket_router(config: Config) -> APIRouter:
    router = APIRouter()

    @router.websocket("/{workspace_id}/events")
    async def events(
        websocket: WebSocket,
        workspace: Annotated[Union[Workspace, WorkspaceError], Depends(get_optional_user_workspace)],
        event_handler: WebsockedtEventHandlerDependency,
    ) -> None:
        logger.debug(f"websocket connection opened for workspace {workspace}")
        await websocket.accept()
        logger.debug(f"websocket connection accepted for workspace {workspace}")
        # check if the user is authorized to listen to this tenant
        if isinstance(workspace, str):
            logger.debug(f"websocket connection closed for workspace {workspace}, user not authorized")
            await websocket.send_json({"error": workspace})
            await websocket.close()
            return

        await event_handler.handle_websocket(workspace.id, websocket)

    return router
