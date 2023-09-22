from typing import Dict, Any, Annotated
from uuid import UUID
from fastapi import WebSocket, Depends

from datetime import datetime
from redis.asyncio import Redis
from fixcloudutils.redis.pub_sub import RedisPubSubListener
from fixbackend.config import ConfigDependency


def get_readonly_redis(config: ConfigDependency) -> Redis:
    return Redis.from_url(config.redis_readonly_url)  # type: ignore


ReadonlyRedisDependency = Annotated[Redis, Depends(get_readonly_redis)]


class WebsocketEventHandler:
    def __init__(self, readonly_redis: ReadonlyRedisDependency) -> None:
        self.readonly_redis = readonly_redis

    async def handle_websocket(self, tenant_id: UUID, websocket: WebSocket) -> None:
        async def redis_message_handler(id: str, at: datetime, publisher: str, kind: str, data: Dict[str, Any]) -> None:
            await websocket.send_json(
                {"type": "event", "id": id, "at": at, "publisher": publisher, "kind": kind, "data": data}
            )

        async with RedisPubSubListener(
            redis=self.readonly_redis,
            channel=f"tenant-events::{tenant_id}",
            handler=redis_message_handler,
        ):
            try:
                while True:
                    await websocket.receive_json()

            except Exception:
                pass


def get_websocket_event_handler(readonly_redis: ReadonlyRedisDependency) -> WebsocketEventHandler:
    return WebsocketEventHandler(readonly_redis)


WebsockedtEventHandlerDependency = Annotated[WebsocketEventHandler, Depends(get_websocket_event_handler)]
