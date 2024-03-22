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
from typing import AsyncIterator

import pytest
from fixcloudutils.types import Json

from fixbackend.streaming_response import streaming_response


@pytest.mark.asyncio
async def test_streaming_json() -> None:
    async def gen() -> AsyncIterator[Json]:
        yield {"a": 1}
        yield {"b": 2}

    fn, media_type = streaming_response("application/json")
    assert [a async for a in fn(gen())] == ["[", '{"a": 1}', ',{"b": 2}', "]"]
    assert media_type == "application/json"
    fn, media_type = streaming_response("application/ndjson")
    assert [a async for a in fn(gen())] == ['{"a": 1}\n', '{"b": 2}\n']
    assert media_type == "application/ndjson"
    fn, media_type = streaming_response("text/csv")
    assert [a async for a in fn(gen())] == ["{'a': 1}\n", "{'b': 2}\n"]
    assert media_type == "text/csv"
