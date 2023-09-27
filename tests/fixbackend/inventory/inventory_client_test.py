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
import uuid

from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.ids import TenantId
from fixbackend.inventory.inventory_client import InventoryClient


async def test_execute_single(inventory_client: InventoryClient) -> None:
    db_access = GraphDatabaseAccess(TenantId(uuid.uuid1()), "server", "database", "username", "password")
    assert [a async for a in inventory_client.execute_single(db_access, "json [1,2,3]")] == ["1", "2", "3"]
