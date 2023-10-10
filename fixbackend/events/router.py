from fastapi import APIRouter, WebSocket
from fixbackend.config import Config
from fixbackend.auth.current_user_dependencies import UserWorkspacesDependency
from fixbackend.events.websocket_event_handler import WebsockedtEventHandlerDependency
from fixbackend.ids import WorkspaceId


def websocket_router(config: Config) -> APIRouter:
    router = APIRouter()

    @router.websocket("/{workspace_id}/events")
    async def events(
        websocket: WebSocket,
        workspace_id: WorkspaceId,
        workspaces: UserWorkspacesDependency,
        event_handler: WebsockedtEventHandlerDependency,
    ) -> None:
        await websocket.accept()
        # check if the user is authorized to listen to this tenant
        if workspace_id not in workspaces:
            await websocket.send_json({"error": "Unauthorized"})
            await websocket.close()
            return

        await event_handler.handle_websocket(workspace_id, websocket)

    return router
