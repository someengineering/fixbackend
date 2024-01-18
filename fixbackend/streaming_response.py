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
from typing import AsyncIterator, Optional, Dict

from fastapi.responses import StreamingResponse
from fixcloudutils.types import JsonElement


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


def streaming_response(
    accept: str, gen: AsyncIterator[JsonElement], headers: Optional[Dict[str, str]] = None
) -> StreamingResponse:
    if accept in ["application/x-ndjson", "application/ndjson"]:
        return StreamingResponse(ndjson_serializer(gen), media_type="application/ndjson", headers=headers)
    elif accept == "application/json":
        return StreamingResponse(json_serializer(gen), media_type="application/json", headers=headers)
    elif accept == "text/csv":
        return StreamingResponse(csv_serializer(gen), media_type="text/csv", headers=headers)
    else:
        return StreamingResponse(json_serializer(gen), media_type="application/json", headers=headers)
