#  Copyright (c) 2023. Some Engineering
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
import json
import typing
from typing import AsyncIterator, Callable, Tuple

from fastapi.responses import StreamingResponse
from fixcloudutils.types import JsonElement
from starlette.background import BackgroundTask
from starlette.responses import ContentStream
from starlette.types import Send

from fixbackend.errors import NotAllowed, ResourceNotFound, WrongState, ClientError


async def json_serializer(input_iterator: AsyncIterator[JsonElement]) -> AsyncIterator[str]:
    yield "["
    flag = False
    async for item in input_iterator:
        pre = "," if flag else ""
        yield pre + json.dumps(item)
        flag = True
    yield "]"


async def ndjson_serializer(input_iterator: AsyncIterator[JsonElement]) -> AsyncIterator[str]:
    async for item in input_iterator:
        yield json.dumps(item) + "\n"


async def csv_serializer(input_iterator: AsyncIterator[JsonElement]) -> AsyncIterator[str]:
    async for item in input_iterator:
        yield str(item) + "\n"


def streaming_response(accept: str) -> Tuple[Callable[[AsyncIterator[JsonElement]], AsyncIterator[str]], str]:
    if accept in ["application/x-ndjson", "application/ndjson"]:
        return ndjson_serializer, "application/ndjson"
    elif accept == "application/json":
        return json_serializer, "application/json"
    elif accept == "text/csv":
        return csv_serializer, "text/csv"
    else:
        return json_serializer, "application/json"


class StreamOnSuccessResponse(StreamingResponse):
    def __init__(
        self,
        content: ContentStream,
        status_code: int = 200,
        headers: typing.Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ) -> None:
        super().__init__(content, status_code, headers, media_type, background)
        self.additional_headers = headers

    async def stream_response(self, send: Send) -> None:
        first = True
        try:
            async for chunk in self.body_iterator:
                if first:  # send response code and headers only when the first element is ready
                    first = False
                    if self.additional_headers:
                        self.init_headers(self.additional_headers)
                    await send({"type": "http.response.start", "status": self.status_code, "headers": self.raw_headers})
                if not isinstance(chunk, bytes):
                    chunk = chunk.encode(self.charset)
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            if first:
                if self.additional_headers:
                    self.init_headers(self.additional_headers)
                await send({"type": "http.response.start", "status": self.status_code, "headers": self.raw_headers})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        except Exception as exc:
            # when an exception occurs after the first chunk is sent, raise. Otherwise handle it.
            if not first:
                raise
            if isinstance(exc, NotAllowed):
                code = 403
            elif isinstance(exc, ResourceNotFound):
                code = 404
            elif isinstance(exc, WrongState):
                code = 409
            elif isinstance(exc, ClientError):
                code = 400
            else:
                code = 500
            await send({"type": "http.response.start", "status": code, "headers": self.raw_headers})
            await send({"type": "http.response.body", "body": str(exc).encode(self.charset), "more_body": False})
