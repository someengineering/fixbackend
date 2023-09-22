from uuid import UUID
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fixbackend.config import Config
from fixbackend.organizations.dependencies import UserTenantsDependency
from fixbackend.events.event_service import EventServiceDependency
import asyncio
from datetime import datetime, timedelta


def websocket_router(config: Config) -> APIRouter:
    router = APIRouter()

    @router.websocket("/events/{tenant_id}")
    async def events(
        websocket: WebSocket, tenant_id: UUID, tenants: UserTenantsDependency, event_service: EventServiceDependency
    ) -> None:
        await websocket.accept()
        # check if the user is authorized to listen to this tenant
        if tenant_id not in tenants:
            await websocket.send_json({"error": "Unauthorized"})
            await websocket.close()
            return

        event_service.register_tenant_listener(tenant_id, websocket)

        last_received_pong: datetime = datetime.utcnow()
        closed = False

        async def receive_messages() -> None:
            try:
                while not closed:
                    message = await websocket.receive_json()
                    match message["type"]:
                        case "pong":
                            nonlocal last_received_pong
                            last_received_pong = datetime.utcnow()
                        case _:
                            await websocket.send_json({"error": "Unknown message type"})
            except WebSocketDisconnect:
                pass

        async with asyncio.TaskGroup() as tg:
            tg.create_task(receive_messages())

        # remove the listener once the connection is closed
        event_service.unregister_tenant_listener(tenant_id, websocket)

    return router
