from typing import Union, cast

from uvicorn._types import (
    ASGI3Application,
    ASGIReceiveCallable,
    ASGISendCallable,
    HTTPScope,
    Scope,
    WebSocketScope,
)


class RealIpMiddleware:
    def __init__(
        self,
        app: "ASGI3Application",
    ) -> None:
        self.app = app

    async def __call__(self, scope: "Scope", receive: ASGIReceiveCallable, send: ASGISendCallable) -> None:
        if scope["type"] in ("http", "websocket"):
            scope = cast(Union["HTTPScope", "WebSocketScope"], scope)

            headers = dict(scope["headers"])

            if b"x-real-ip" in headers:
                # Determine the client address from the last trusted IP in the X-Real-Ip header.
                host = headers[b"x-real-ip"].decode()
                # we lost the port information, so we set it to 0
                port = 0
                scope["client"] = (host, port)

        return await self.app(scope, receive, send)
