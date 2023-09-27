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

    response = streaming_response("application/json", gen())
    assert [a async for a in response.body_iterator] == ["[", '{"a": 1}', ',{"b": 2}', "]"]
    response = streaming_response("application/ndjson", gen())
    assert [a async for a in response.body_iterator] == ['{"a": 1}\n', '{"b": 2}\n']
