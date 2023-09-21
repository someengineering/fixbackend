from typing import Dict, Set, Any, Annotated
from uuid import UUID
from fastapi import WebSocket, Depends
import asyncio


class EventService:
    def __init__(self) -> None:
        self.connected_tenants: Dict[UUID, Set[WebSocket]] = {}

    def register_tenant_listener(self, tenant_id: UUID, websocket: WebSocket) -> None:
        self.connected_tenants.setdefault(tenant_id, set()).add(websocket)

    def unregister_tenant_listener(self, tenant_id: UUID, websocket: WebSocket) -> None:
        self.connected_tenants[tenant_id].remove(websocket)

    async def send_to_tenant(self, tenant_id: UUID, event: Dict[str, Any]) -> None:
        async with asyncio.TaskGroup() as tg:
            for websocket in self.connected_tenants[tenant_id]:
                tg.create_task(websocket.send_json(event))


def get_event_service() -> EventService:
    return EventService()


EventServiceDependency = Annotated[EventService, Depends(get_event_service)]
