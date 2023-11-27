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
from types import SimpleNamespace
from typing import List, cast
from uuid import uuid4

import pytest
from fixcloudutils.types import Json
from httpx import AsyncClient, MockTransport, Request, Response

from fixbackend.domain_events.events import AwsAccountDeleted
from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import CloudAccountId, FixCloudAccountId, NodeId, WorkspaceId
from fixbackend.inventory.inventory_client import InventoryClient
from fixbackend.inventory.inventory_service import InventoryService, dict_values_by
from fixbackend.inventory.schemas import (
    BenchmarkAccountSummary,
    CheckSummary,
    NoVulnerabilitiesChanged,
    ReportSummary,
    SearchCloudResource,
    SearchRequest,
    HistorySearch,
    HistoryChange,
)
from tests.fixbackend.conftest import RequestHandlerMock, json_response, nd_json_response
from fixbackend.domain_events.subscriber import DomainEventSubscriber

db = GraphDatabaseAccess(WorkspaceId(uuid.uuid1()), "server", "database", "username", "password")

neighborhood: List[Json] = [
    {"id": "some_node_id", "type": "node", "reported": {"kind": "kubernetes_pod"}},
    {"id": "successor_id", "type": "node", "reported": {"kind": "kubernetes_secret"}},
    {"id": "predecessor_id", "type": "node", "reported": {"kind": "kubernetes_stateful_set"}},
    {"type": "edge", "from": "predecessor_id", "to": "some_node_id"},
    {"type": "edge", "from": "some_node_id", "to": "successor_id"},
]


@pytest.fixture
def mocked_answers(
    request_handler_mock: RequestHandlerMock,
    benchmark_json: List[Json],
    azure_virtual_machine_resource_json: Json,
) -> RequestHandlerMock:
    async def mock(request: Request) -> Response:
        content = request.content.decode("utf-8")
        if request.url.path == "/cli/execute" and content.endswith("jq --no-rewrite .group"):
            return nd_json_response(
                [{"id": "123", "name": "foo", "cloud": "aws"},  # fmt: skip
                 {"id": "234", "name": "bla", "cloud": "gcp"}]  # fmt: skip
            )
        elif request.url.path == "/cli/execute" and content.endswith("list --json-table"):
            return nd_json_response(
                [{"columns": [{"name": "name", "kind": "string", "display": "Name"}, {"name": "some_int", "kind": "int32", "display": "Some Int"}]},  # fmt: skip
                 {"id": "123", "row": {"name": "a", "some_int": 1}}]  # fmt: skip
            )
        elif request.url.path == "/cli/execute" and content.startswith("history --change node_"):
            return nd_json_response(
                [{"count": 1, "group": {"account_id": "123", "severity": "critical", "kind": "gcp_disk"}},  # fmt: skip
                 {"count": 87, "group": {"account_id": "234", "severity": "medium", "kind": "aws_instance"}}],  # fmt: skip
            )
        elif request.url.path == "/cli/execute" and content == "report benchmark load benchmark_name | dump":
            return nd_json_response(benchmark_json)
        elif request.url.path == "/cli/execute" and "<-[0:2]->" in content:
            return nd_json_response(neighborhood)
        elif request.url.path == "/report/checks":
            return json_response([{"categories": [], "detect": {"resoto": "is(aws_s3_bucket)"}, "id": "aws_c1", "provider": "aws", "remediation": {"kind": "resoto_core_report_check_remediation", "text": "You can enable Public Access Block at the account level to prevent the exposure of your data stored in S3.", "url": "https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html", }, "result_kind": "aws_s3_bucket", "risk": "Public access policies may be applied to sensitive data buckets.", "service": "s3", "severity": "high", "title": "Check S3 Account Level Public Access Block."}])  # fmt: skip
        elif request.url.path == "/report/benchmarks":
            return json_response(
                [{"clouds": ["aws"], "description": "Test AWS", "framework": "CIS", "id": "aws_test", "report_checks": [{"id": "aws_c1", "severity": "high"}, {"id": "aws_c2", "severity": "critical"}], "title": "AWS Test", "version": "0.1"},  # fmt: skip
                 {"clouds": ["gcp"], "description": "Test GCP", "framework": "CIS", "id": "gcp_test", "report_checks": [{"id": "gcp_c1", "severity": "low"}, {"id": "gcp_c2", "severity": "medium"}], "title": "GCP Test", "version": "0.2"}]  # fmt: skip
            )
        elif request.url.path == "/graph/resoto/search/list" and content == "is (account)":
            return nd_json_response(
                [{"id": "n1", "type": "node", "reported": {"id": "234", "name": "account 1"}, "ancestors": {"cloud": {"reported": {"name": "gcp", "id": "gcp"}}}},  # fmt: skip
                 {"id": "n2", "type": "node", "reported": {"id": "123", "name": "account 2"}, "ancestors": {"cloud": {"reported": {"name": "aws", "id": "aws"}}}}]  # fmt: skip
            )
        elif request.url.path == "/graph/resoto/search/aggregate":
            return nd_json_response(
                [{"group": {"check_id": "aws_c1", "severity": "low", "account_id": "123", "account_name": "t1", "cloud": "aws"}, "sum_of_1": 8},  # fmt: skip
                 {"group": {"check_id": "gcp_c2", "severity": "critical", "account_id": "234", "account_name": "t2", "cloud": "gcp"}, "sum_of_1": 2}]  # fmt: skip
            )
        elif request.url.path == "/graph/resoto/node/some_node_id":
            return json_response(azure_virtual_machine_resource_json)
        elif request.url.path == "/graph/resoto/model":
            return json_response([{"fqn": "123", "metadata": {"name": "Some name"}}])
        else:
            raise AttributeError(f"Unexpected request: {request.url.path} with content {content}")

    request_handler_mock.append(mock)
    return request_handler_mock


async def test_benchmark_command(
    inventory_service: InventoryService, benchmark_json: List[Json], mocked_answers: RequestHandlerMock
) -> None:
    response = [a async for a in await inventory_service.benchmark(db, "benchmark_name")]
    assert response == benchmark_json


async def test_summary(inventory_service: InventoryService, mocked_answers: RequestHandlerMock) -> None:
    summary = await inventory_service.summary(db)
    assert len(summary.benchmarks) == 2
    assert summary.overall_score == 42
    # checks summary
    assert summary.check_summary.available_checks == 4
    assert summary.check_summary.failed_checks == 2
    assert summary.check_summary.failed_checks_by_severity == {"critical": 1, "low": 1}
    # account checks summary
    assert summary.account_check_summary.available_checks == 8
    assert summary.account_check_summary.failed_checks == 2
    assert summary.account_check_summary.failed_checks_by_severity == {"critical": 1, "low": 1}
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


async def test_no_graph_db_access(
    domain_event_subscriber: DomainEventSubscriber, graph_database_access_manager: GraphDatabaseAccessManager
) -> None:
    async def app(_: Request) -> Response:
        return Response(status_code=400, content="[HTTP 401][ERR 11] not authorized to execute this request")

    async_client = AsyncClient(transport=MockTransport(app))
    async with InventoryClient("http://localhost:8980", client=async_client) as client:
        async with InventoryService(client, graph_database_access_manager, domain_event_subscriber) as service:
            assert await service.summary(db) == ReportSummary(
                check_summary=CheckSummary(available_checks=0, failed_checks=0, failed_checks_by_severity={}),
                account_check_summary=CheckSummary(available_checks=0, failed_checks=0, failed_checks_by_severity={}),
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


async def test_search_list(inventory_service: InventoryService, mocked_answers: RequestHandlerMock) -> None:
    expected = [
        {
            "columns": [
                {"name": "name", "kind": "string", "display": "Name"},
                {"name": "some_int", "kind": "int32", "display": "Some Int"},
            ]
        },
        {"id": "123", "row": {"name": "a", "some_int": 1}},
    ]
    # simple search against the default graph
    request = SearchRequest(query="is(account) and name==foo")
    result = [e async for e in await inventory_service.search_table(db, request)]
    assert result == expected
    # search in history data
    request = SearchRequest(query="is(account) and name==foo", history=HistorySearch(change=HistoryChange.node_created))
    result = [e async for e in await inventory_service.search_table(db, request)]
    assert result == expected


async def test_search_start_data(inventory_service: InventoryService, mocked_answers: RequestHandlerMock) -> None:
    result = [
        SearchCloudResource(id="234", name="bla", cloud="gcp"),
        SearchCloudResource(id="123", name="foo", cloud="aws"),
    ]
    start_data = await inventory_service.search_start_data(db)
    assert start_data.accounts == result
    assert start_data.regions == result
    result[1].name = "Some name"  # kind name is looked up and changed
    assert start_data.kinds == result


async def test_resource(
    inventory_service: InventoryService, mocked_answers: RequestHandlerMock, azure_virtual_machine_resource_json: Json
) -> None:
    res = await inventory_service.resource(db, NodeId("some_node_id"))
    assert res["neighborhood"] == neighborhood
    assert res["resource"] == azure_virtual_machine_resource_json
    assert len(res["resource"]["security"]["issues"]) == 1  # resource has one issue
    assert len(res["failing_checks"]) == 1  # one failing check is loaded
    assert res["failing_checks"][0]["id"] == res["resource"]["security"]["issues"][0]["check"]  # check id is the same


@pytest.mark.asyncio
async def test_account_deleted(domain_event_subscriber: DomainEventSubscriber) -> None:
    cloud_account_id = CloudAccountId("123")

    async def delete_account(
        access: GraphDatabaseAccess,
        cloud: str,
        account_id: CloudAccountId,
        graph: str = "resoto",
    ) -> None:
        assert access == db
        assert cloud == "aws"
        assert account_id == cloud_account_id
        assert graph == "resoto"

    async def get_db_access(workspace_id: WorkspaceId) -> GraphDatabaseAccess:
        return db

    inventory_client = cast(InventoryClient, SimpleNamespace(delete_account=delete_account))
    db_manager = cast(GraphDatabaseAccessManager, SimpleNamespace(get_database_access=get_db_access))
    inventory_service = InventoryService(
        inventory_client,
        db_manager,
        domain_event_subscriber,
    )
    message = AwsAccountDeleted(FixCloudAccountId(uuid4()), WorkspaceId(uuid4()), CloudAccountId("123"))
    await inventory_service.process_account_deleted(message)
