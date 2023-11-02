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
from fixbackend.ids import WorkspaceId
from fixbackend.inventory.inventory_client import InventoryClient
from fixbackend.inventory.inventory_service import InventoryService, dict_values_by
from fixbackend.inventory.schemas import (
    ReportSummary,
    NoVulnerabilitiesChanged,
    BenchmarkAccountSummary,
    CheckSummary,
    SearchCloudResource,
)

db = GraphDatabaseAccess(WorkspaceId(uuid.uuid1()), "server", "database", "username", "password")


async def test_benchmark_command(inventory_service: InventoryService, benchmark_json: List[Json]) -> None:
    response = [a async for a in await inventory_service.benchmark(db, "benchmark_name")]
    assert response == benchmark_json


async def test_summary(inventory_service: InventoryService) -> None:
    summary = await inventory_service.summary(db)
    assert len(summary.benchmarks) == 2
    assert summary.overall_score == 42
    # checks summary
    assert summary.check_summary.available_checks == 4
    assert summary.check_summary.failed_checks == 2
    assert summary.check_summary.failed_checks_by_severity == {"critical": 1, "low": 1}
    # check benchmarks
    b1, b2 = summary.benchmarks
    assert b1.id == "aws_test"
    assert b1.clouds == ["aws"]
    assert b1.account_summary == {"123": BenchmarkAccountSummary(score=85, failed_checks={"low": 1})}
    assert b2.id == "gcp_test"
    assert b2.clouds == ["gcp"]
    assert b2.account_summary == {"234": BenchmarkAccountSummary(score=0, failed_checks={"critical": 1})}
    assert len(summary.accounts) == 2
    # check accounts
    gcp, aws = summary.accounts
    assert gcp.id == "234"
    assert gcp.name == "account 1"
    assert gcp.cloud == "gcp"
    assert gcp.score == 0
    assert aws.id == "123"
    assert aws.name == "account 2"
    assert aws.cloud == "aws"
    assert aws.score == 85
    # check becoming vulnerable
    assert summary.changed_vulnerable.accounts_selection == ["123", "234"]
    assert summary.changed_vulnerable.resource_count_by_severity == {"critical": 1, "medium": 87}
    assert summary.changed_vulnerable.resource_count_by_kind_selection == {"aws_instance": 87, "gcp_disk": 1}
    assert summary.changed_compliant.accounts_selection == ["123", "234"]
    assert summary.changed_compliant.resource_count_by_severity == {"critical": 1, "medium": 87}
    assert summary.changed_compliant.resource_count_by_kind_selection == {"aws_instance": 87, "gcp_disk": 1}
    # top checks
    assert len(summary.top_checks) == 1


async def test_no_graph_db_access() -> None:
    async def app(_: Request) -> Response:
        return Response(status_code=400, content="[HTTP 401][ERR 11] not authorized to execute this request")

    async_client = AsyncClient(transport=MockTransport(app))
    async with InventoryClient("http://localhost:8980", client=async_client) as client:
        async with InventoryService(client) as service:
            assert await service.summary(db) == ReportSummary(
                check_summary=CheckSummary(available_checks=0, failed_checks=0, failed_checks_by_severity={}),
                overall_score=0,
                accounts=[],
                benchmarks=[],
                changed_vulnerable=NoVulnerabilitiesChanged,
                changed_compliant=NoVulnerabilitiesChanged,
                top_checks=[],
            )


async def test_dict_values_by() -> None:
    # check order
    inv = {1: [11, 12, 13], 2: [21, 22, 23], 0: [1, 2, 3]}
    assert [a for a in dict_values_by(inv, lambda x: x)] == [21, 22, 23, 11, 12, 13, 1, 2, 3]
    assert [a for a in dict_values_by(inv, lambda x: -x)] == [1, 2, 3, 11, 12, 13, 21, 22, 23]
    # make sure the result is unique
    inv = {1: [1, 2, 3, 11, 12, 13], 2: [1, 2, 3, 11, 12, 13, 21, 22, 23], 0: [1, 2, 3]}
    assert [a for a in dict_values_by(inv, lambda x: -x)] == [1, 2, 3, 11, 12, 13, 21, 22, 23]


async def test_search_start_data(inventory_service: InventoryService) -> None:
    result = [
        SearchCloudResource(id="123", name="foo", cloud="aws"),
        SearchCloudResource(id="234", name="bla", cloud="gcp"),
    ]
    start_data = await inventory_service.search_start_data(db)
    assert start_data.accounts == result
    assert start_data.regions == result
    assert start_data.kinds == result
