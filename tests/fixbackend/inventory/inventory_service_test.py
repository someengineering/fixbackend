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
from httpx import AsyncClient, Response, Request, MockTransport

from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.ids import TenantId
from fixbackend.inventory.inventory_client import InventoryClient
from fixbackend.inventory.inventory_service import InventoryService
from fixbackend.inventory.schemas import ReportSummary

db = GraphDatabaseAccess(TenantId(uuid.uuid1()), "server", "database", "username", "password")


async def test_benchmark_command(inventory_service: InventoryService, benchmark_json: List[Json]) -> None:
    response = [a async for a in await inventory_service.benchmark(db, "benchmark_name")]
    assert response == benchmark_json


async def test_summary(inventory_service: InventoryService) -> None:
    summary = await inventory_service.summary(db)
    assert len(summary.benchmarks) == 2
    b1, b2 = summary.benchmarks
    assert b1.id == "aws_test"
    assert b1.clouds == ["aws"]
    assert b1.failed_checks == {"123": {"low": 1}}
    assert b2.id == "gcp_test"
    assert b2.clouds == ["gcp"]
    assert b2.failed_checks == {"234": {"critical": 1}}
    assert len(summary.accounts) == 2
    gcp, aws = summary.accounts
    assert gcp.id == "234"
    assert gcp.name == "account 1"
    assert gcp.cloud == "gcp"
    assert aws.id == "123"
    assert aws.name == "account 2"
    assert aws.cloud == "aws"


async def test_no_graph_db_access() -> None:
    async def app(_: Request) -> Response:
        return Response(status_code=400, content="[HTTP 401][ERR 11] not authorized to execute this request")

    async_client = AsyncClient(transport=MockTransport(app))
    async with InventoryClient("http://localhost:8980", client=async_client) as client:
        async with InventoryService(client) as service:
            assert await service.summary(db) == ReportSummary(accounts=[], benchmarks=[])
