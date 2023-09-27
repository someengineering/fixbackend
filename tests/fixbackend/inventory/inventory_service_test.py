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
from typing import List

from fixcloudutils.types import Json

from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.ids import TenantId
from fixbackend.inventory.inventory_service import InventoryService, AccountSummary


async def test_benchmark_command(inventory_service: InventoryService, benchmark_json: List[Json]) -> None:
    db = GraphDatabaseAccess(TenantId(uuid.uuid1()), "server", "database", "username", "password")
    response = [a async for a in await inventory_service.benchmark(db, "benchmark_name")]
    assert response == benchmark_json


async def test_summary(inventory_service: InventoryService) -> None:
    db = GraphDatabaseAccess(TenantId(uuid.uuid1()), "server", "database", "username", "password")
    summaries = await inventory_service.summary(db)
    assert len(summaries) == 2
    aws, gcp = summaries
    assert aws.id == "aws_test"
    assert aws.clouds == ["aws"]
    assert aws.accounts == [AccountSummary(id="123", name="t1", cloud="aws", failed_by_severity={"low": 1})]
    assert gcp.id == "gcp_test"
    assert gcp.clouds == ["gcp"]
    assert gcp.accounts == [AccountSummary(id="234", name="t2", cloud="gcp", failed_by_severity={"critical": 1})]
