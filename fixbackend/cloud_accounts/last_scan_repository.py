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

from fixbackend.cloud_accounts.models import LastScanInfo
from fixbackend.domain_events.converter import converter
from fixbackend.ids import WorkspaceId
from fixbackend.keyvalue.json_kv import JsonStore


class LastScanRepository:
    def __init__(self, kv_store: JsonStore) -> None:
        self.prefix = "last_scan:"
        self.kv_store = kv_store

    async def set_last_scan(self, workspace_id: WorkspaceId, last_scan_statistics: LastScanInfo) -> None:
        await self.kv_store.set(self.prefix + ":" + str(workspace_id), converter.unstructure(last_scan_statistics))

    async def get_last_scan(self, workspace_id: WorkspaceId) -> Optional[LastScanInfo]:
        json = await self.kv_store.get(self.prefix + ":" + str(workspace_id))
        if json is None:
            return None
        return converter.structure(json, LastScanInfo)
