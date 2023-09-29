from datetime import datetime
from typing import Dict, Any, Annotated

from fastapi import WebSocket, Depends
from fixcloudutils.redis.pub_sub import RedisPubSubListener
from redis.asyncio import Redis

from fixbackend.dependencies import FixDependency
from fixbackend.ids import TenantId


class WebsocketEventHandler:
    def __init__(self, readonly_redis: Redis) -> None:
        self.readonly_redis = readonly_redis

    async def handle_websocket(self, tenant_id: TenantId, websocket: WebSocket) -> None:
        async def redis_message_handler(id: str, at: datetime, publisher: str, kind: str, data: Dict[str, Any]) -> None:
            await websocket.send_json(
                {"type": "event", "id": id, "at": at, "publisher": publisher, "kind": kind, "data": data}
            )

        async def ignore_incoming_messages(websocket: WebSocket) -> None:
            while True:
                await websocket.receive()

        async with RedisPubSubListener(
            redis=self.readonly_redis,
            channel=f"tenant-events::{tenant_id}",
            handler=redis_message_handler,
        ):
            try:
                await ignore_incoming_messages(websocket)
            except Exception:
                pass


def get_websocket_event_handler(fix: FixDependency) -> WebsocketEventHandler:
    return WebsocketEventHandler(fix.readonly_redis)


WebsockedtEventHandlerDependency = Annotated[WebsocketEventHandler, Depends(get_websocket_event_handler)]
