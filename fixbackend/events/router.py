from fastapi import APIRouter, WebSocket
from fixbackend.config import Config
from fixbackend.auth.current_user_dependencies import UserTenantsDependency
from fixbackend.events.websocket_event_handler import WebsockedtEventHandlerDependency
from fixbackend.ids import TenantId


def websocket_router(config: Config) -> APIRouter:
    router = APIRouter()

    @router.websocket("/{organization_id}/events")
    async def events(
        websocket: WebSocket,
        organization_id: TenantId,
        organizations: UserTenantsDependency,
        event_handler: WebsockedtEventHandlerDependency,
    ) -> None:
        await websocket.accept()
        # check if the user is authorized to listen to this tenant
        if organization_id not in organizations:
            await websocket.send_json({"error": "Unauthorized"})
            await websocket.close()
            return

        await event_handler.handle_websocket(organization_id, websocket)

    return router
