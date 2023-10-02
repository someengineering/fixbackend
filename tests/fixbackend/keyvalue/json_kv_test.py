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


import pytest

from fixbackend.keyvalue.json_kv import JsonStoreImpl
from fixbackend.types import AsyncSessionMaker


@pytest.mark.asyncio
async def test_json_store(async_session_maker: AsyncSessionMaker) -> None:
    json_store = JsonStoreImpl(async_session_maker)
    key = "foo"
    value = {"a": 1, "b": "2", "c": ["3"], "d": {"da": 4, "db": "5", "dc": ["6"]}}
    # insert
    await json_store.set(key, value)
    # insert is idempotent
    await json_store.set(key, value)
    # get
    assert await json_store.get(key) == value
    # update
    await json_store.set(key, "bar")
    assert await json_store.get(key) == "bar"
    # delete
    await json_store.delete(key)
    assert await json_store.get(key) is None
    # delete is idempotent
    await json_store.delete(key)
