from fastapi import APIRouter, WebSocket
from fixbackend.config import Config
from fixbackend.organizations.dependencies import UserOrganizationsDependency
from fixbackend.events.websocket_event_handler import WebsockedtEventHandlerDependency
from fixbackend.ids import OrganizationId


def websocket_router(config: Config) -> APIRouter:
    router = APIRouter()

    @router.websocket("/events/{organization_id}")
    async def events(
        websocket: WebSocket,
        organization_id: OrganizationId,
        organizations: UserOrganizationsDependency,
        event_handler: WebsockedtEventHandlerDependency,
    ) -> None:
        await websocket.accept()
        # check if the user is authorized to listen to this tenant
        if organization_id not in organizations:
            await websocket.send_json({"error": "Unauthorized"})
            await websocket.close()
            return

        tenant_id = organizations[organization_id]

        await event_handler.handle_websocket(tenant_id, websocket)

    return router
