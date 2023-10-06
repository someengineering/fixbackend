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

from abc import ABC, abstractmethod
from typing import Annotated, Optional

from fastapi import Depends
from fixcloudutils.types import JsonElement
from sqlalchemy import JSON, String, delete
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.base_model import Base
from fixbackend.db import AsyncSessionMakerDependency
from fixbackend.types import AsyncSessionMaker


class JsonStore(ABC):
    @abstractmethod
    async def get(self, key: str) -> Optional[JsonElement]:
        pass

    @abstractmethod
    async def set(self, key: str, value: JsonElement) -> None:
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        pass


class JsonEntry(Base):
    __tablename__ = "key_value_json"

    key: Mapped[str] = mapped_column(String(length=64), primary_key=True)
    value: Mapped[JsonElement] = mapped_column(JSON, nullable=False)


class JsonStoreImpl(JsonStore):
    def __init__(self, session_maker: AsyncSessionMaker):
        self.session_maker = session_maker

    async def get(self, key: str) -> Optional[JsonElement]:
        async with self.session_maker() as session:
            entry = await session.get(JsonEntry, key)
            if entry is None:
                return None
            return entry.value

    async def set(self, key: str, value: JsonElement) -> None:
        async with self.session_maker() as session:
            insert_statement = insert(JsonEntry).values(key=key, value=value)
            upsert_statement = insert_statement.on_duplicate_key_update(value=insert_statement.inserted.value)
            await session.execute(upsert_statement)

    async def delete(self, key: str) -> None:
        async with self.session_maker() as session:
            statement = delete(JsonEntry).where(JsonEntry.key == key)
            await session.execute(statement)


def get_json_store(session_maker: AsyncSessionMakerDependency) -> JsonStore:
    return JsonStoreImpl(session_maker)


JsonStoreDependency = Annotated[JsonStore, Depends(get_json_store)]
