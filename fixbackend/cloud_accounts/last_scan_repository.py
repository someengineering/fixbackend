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

from typing import Optional

from fixcloudutils.types import JsonElement
from sqlalchemy import JSON, String
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.base_model import Base
from fixbackend.cloud_accounts.models import LastScanInfo
from fixbackend.domain_events.converter import converter
from fixbackend.ids import WorkspaceId
from fixbackend.types import AsyncSessionMaker


class Entry(Base):
    __tablename__ = "last_scan_reposotory"

    key: Mapped[str] = mapped_column(String(length=64), primary_key=True)
    value: Mapped[JsonElement] = mapped_column(JSON, nullable=False)


class LastScanRepository:
    def __init__(self, session_maker: AsyncSessionMaker) -> None:
        self.session_maker = session_maker

    async def set_last_scan(self, workspace_id: WorkspaceId, last_scan_statistics: LastScanInfo) -> None:
        async with self.session_maker() as session:
            value = converter.unstructure(last_scan_statistics)
            insert_statement = insert(Entry).values(key=str(workspace_id), value=value)
            upsert_statement = insert_statement.on_duplicate_key_update(value=insert_statement.inserted.value)
            await session.execute(upsert_statement)
            await session.commit()

    async def get_last_scan(self, workspace_id: WorkspaceId) -> Optional[LastScanInfo]:
        async with self.session_maker() as session:
            entry = await session.get(Entry, str(workspace_id))
            if entry is None:
                return None
            return converter.structure(entry.value, LastScanInfo)
