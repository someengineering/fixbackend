from uuid import UUID
from fastapi import APIRouter, WebSocket
from fixbackend.config import Config
from fixbackend.organizations.dependencies import UserTenantsDependency
from fixbackend.events.websocket_event_handler import WebsockedtEventHandlerDependency


def websocket_router(config: Config) -> APIRouter:
    router = APIRouter()

    @router.websocket("/events/{tenant_id}")
    async def events(
        websocket: WebSocket,
        tenant_id: UUID,
        tenants: UserTenantsDependency,
        event_handler: WebsockedtEventHandlerDependency,
    ) -> None:
        await websocket.accept()
        # check if the user is authorized to listen to this tenant
        if tenant_id not in tenants:
            await websocket.send_json({"error": "Unauthorized"})
            await websocket.close()
            return

        await event_handler.handle_websocket(tenant_id, websocket)

    return router
