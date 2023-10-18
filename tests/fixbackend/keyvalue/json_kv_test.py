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
import asyncio
from fixcloudutils.types import JsonElement
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker


@pytest.mark.asyncio
async def test_json_store(async_session_maker: AsyncSessionMaker, db_engine: AsyncEngine) -> None:
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

    the_real_json_store = JsonStoreImpl(async_sessionmaker(db_engine))

    def increment(key: str, value: JsonElement) -> JsonElement:
        match value:
            case None:
                return 1
            case i if isinstance(i, int):
                return i + 1
            case _:
                raise ValueError(f"Unexpected value {value}")

    # concurrency test of atomic_update
    nr_increments = 42
    increment_key = "increment_me"
    async with asyncio.TaskGroup() as tg:
        for i in range(nr_increments):
            tg.create_task(the_real_json_store.atomic_update(increment_key, increment))

    assert await the_real_json_store.get(increment_key) == nr_increments
