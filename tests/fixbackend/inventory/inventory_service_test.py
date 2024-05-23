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
import json
import uuid
from datetime import timedelta
from typing import List
from uuid import uuid4

import pytest
from fixcloudutils.types import Json
from httpx import Request, Response

from fixbackend.auth.models import User
from fixbackend.domain_events.events import (
    CloudAccountDeleted,
    CloudAccountNameChanged,
    WorkspaceCreated,
    ProductTierChanged,
)
from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.ids import (
    CloudAccountId,
    CloudNames,
    FixCloudAccountId,
    NodeId,
    WorkspaceId,
    UserCloudAccountName,
    CloudName,
    UserId,
    ProductTier,
)
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
    ReportConfig,
    SortOrder,
)
from fixbackend.utils import uid
from fixbackend.workspaces.models import Workspace
from tests.fixbackend.conftest import RequestHandlerMock, json_response, nd_json_response, eventually

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
    example_check: Json,
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
                [{"columns": [{"name": "name", "kind": "string", "display": "Name", "path": "/reported.name"}, {"name": "some_int", "kind": "int32", "display": "Some Int", "path": "/reported.some_int"}]},  # fmt: skip
                 {"id": "123", "row": {"name": "a", "some_int": 1}}]  # fmt: skip
            )
        elif request.url.path == "/cli/execute" and content.endswith("list --csv"):
            return nd_json_response(["name,some_int", "a,1"])
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
            return json_response([example_check])
        elif request.url.path == "/report/benchmarks":
            return json_response(
                [{"clouds": ["aws"], "description": "Test AWS", "framework": "CIS", "id": "aws_test", "report_checks": [{"id": "aws_c1", "severity": "high"}, {"id": "aws_c2", "severity": "critical"}], "title": "AWS Test", "version": "0.1"},  # fmt: skip
                 {"clouds": ["gcp"], "description": "Test GCP", "framework": "CIS", "id": "gcp_test", "report_checks": [{"id": "gcp_c1", "severity": "low"}, {"id": "gcp_c2", "severity": "medium"}], "title": "GCP Test", "version": "0.2"}]  # fmt: skip
            )
        elif request.url.path == "/graph/fix/search/aggregate" and content.startswith("search /ancestors.account.reported.id!=null"):  # fmt: skip
            return nd_json_response(
                [{"group": {"account_id": "123", "account_name": "account 2", "cloud_name": "aws", "severity": "medium"}, "count": 50000},  # fmt: skip
                 {"group": {"account_id": "123", "account_name": "account 2", "cloud_name": "aws", "severity": "high"}, "count": 4321},  # fmt: skip
                 {"group": {"account_id": "234", "account_name": "account 1", "cloud_name": "gcp", "severity": "medium"}, "count": 12345}]  # fmt: skip
            )
        elif request.url.path == "/graph/fix/search/aggregate" and content.startswith("search /security.has_issues==true"):  # fmt: skip
            return nd_json_response(
                [{"group": {"check_id": "aws_c1", "severity": "low", "account_id": "123", "account_name": "t1", "cloud": "aws"}, "count": 8},  # fmt: skip
                 {"group": {"check_id": "gcp_c2", "severity": "critical", "account_id": "234", "account_name": "t2", "cloud": "gcp"}, "count": 2}]  # fmt: skip
            )
        elif request.url.path == "/graph/fix/node/some_node_id":
            return json_response(azure_virtual_machine_resource_json)
        elif request.url.path == "/graph/fix/model":
            return json_response([{"fqn": "123", "metadata": {"name": "Some name"}}])
        elif request.url.path == "/timeseries/infected_resources":
            return nd_json_response(
                [
                    {"at": "2023-12-05T16:52:38Z", "group": {"severity": "critical"}, "v": 5},
                    {"at": "2023-12-05T16:52:38Z", "group": {"severity": "high"}, "v": 18.6},
                    {"at": "2023-12-05T16:52:38Z", "group": {"severity": "medium"}, "v": 47},
                    {"at": "2023-12-05T16:52:38Z", "group": {"severity": "low"}, "v": 5},
                    {"at": "2023-12-06T16:52:38Z", "group": {"severity": "critical"}, "v": 1},
                    {"at": "2023-12-06T16:52:38Z", "group": {"severity": "high"}, "v": 12},
                    {"at": "2023-12-06T16:52:38Z", "group": {"severity": "medium"}, "v": 26.92307692307692},
                    {"at": "2023-12-06T16:52:38Z", "group": {"severity": "low"}, "v": 2},
                ]
            )
        elif request.url.path == "/config/fix.report.config":
            return json_response(
                dict(
                    report_config=dict(ignore_checks=["a", "b"], override_values={"foo": "bla"}),
                    ignore_benchmarks=["b1"],
                )
            )
        elif request.url.path == "/config/fix.core":
            return json_response(json.loads(request.content))
        else:
            raise AttributeError(f"Unexpected request: {request.url.path} with content {content}")

    request_handler_mock.append(mock)
    return request_handler_mock


async def test_benchmark_command(
    inventory_service: InventoryService, benchmark_json: List[Json], mocked_answers: RequestHandlerMock
) -> None:
    async with inventory_service.benchmark(db, "benchmark_name") as result:
        response = [a async for a in result]
        assert response == benchmark_json


async def test_summary(inventory_service: InventoryService, mocked_answers: RequestHandlerMock) -> None:
    summary = await inventory_service.summary(db)
    assert len(summary.benchmarks) == 2
    assert summary.overall_score == 42
    # checks summary
    assert summary.check_summary.available_checks == 4
    assert summary.check_summary.failed_checks == 2
    assert summary.check_summary.failed_checks_by_severity == {"critical": 1, "low": 1}
    assert summary.check_summary.failed_resources == 66666
    assert summary.check_summary.failed_resources_by_severity == {"high": 4321, "medium": 62345}
    # check benchmarks
    b1, b2 = summary.benchmarks
    assert b1.id == "aws_test"
    assert b1.clouds == ["aws"]
    assert b1.account_summary == {
        "123": BenchmarkAccountSummary(score=85, failed_checks={"low": 1}, failed_resource_checks={"low": 8})
    }
    assert b2.id == "gcp_test"
    assert b2.clouds == ["gcp"]
    assert b2.account_summary == {
        "234": BenchmarkAccountSummary(score=0, failed_checks={"critical": 1}, failed_resource_checks={"critical": 2})
    }
    assert len(summary.accounts) == 2
    # check accounts
    gcp, aws = summary.accounts
    assert gcp.id == "234"
    assert gcp.name == "account 1"
    assert gcp.cloud == "gcp"
    assert gcp.score == 0
    assert gcp.failed_resources_by_severity == {"medium": 12345}
    assert aws.id == "123"
    assert aws.name == "account 2"
    assert aws.cloud == "aws"
    assert aws.score == 85
    assert aws.failed_resources_by_severity == {"medium": 50000, "high": 4321}
    # check becoming vulnerable
    assert summary.changed_vulnerable.accounts_selection == ["234", "123"]
    assert summary.changed_vulnerable.resource_count_by_severity == {"critical": 1, "medium": 87}
    assert summary.changed_vulnerable.resource_count_by_kind_selection == {"aws_instance": 87, "gcp_disk": 1}
    assert summary.changed_compliant.accounts_selection == ["234", "123"]
    assert summary.changed_compliant.resource_count_by_severity == {"critical": 1, "medium": 87}
    assert summary.changed_compliant.resource_count_by_kind_selection == {"aws_instance": 87, "gcp_disk": 1}
    # top checks
    assert len(summary.top_checks) == 1
    tc = summary.top_checks[0]
    assert tc["benchmarks"] == [{"id": "aws_test", "title": "AWS Test"}]
    # vulnerable resources timeseries
    assert summary.vulnerable_resources is not None
    assert summary.vulnerable_resources.name == "infected_resources"
    assert len(summary.vulnerable_resources.data) == 8


async def test_no_graph_db_access(
    inventory_service: InventoryService,
    request_handler_mock: RequestHandlerMock,
) -> None:
    async def app(_: Request) -> Response:
        return Response(status_code=400, content="[HTTP 401][ERR 11] not authorized to execute this request")

    request_handler_mock.append(app)
    empty = CheckSummary(
        available_checks=0,
        failed_checks=0,
        failed_checks_by_severity={},
        available_resources=0,
        failed_resources=0,
        failed_resources_by_severity={},
    )
    assert await inventory_service.summary(db) == ReportSummary(
        check_summary=empty,
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


async def test_search_table(inventory_service: InventoryService, mocked_answers: RequestHandlerMock) -> None:
    expected = [
        {
            "columns": [
                {"name": "name", "kind": "string", "display": "Name", "path": "/reported.name"},
                {"name": "some_int", "kind": "int32", "display": "Some Int", "path": "/reported.some_int"},
            ]
        },
        {"id": "123", "row": {"name": "a", "some_int": 1}},
    ]
    # simple search against the default graph
    request = SearchRequest(query="is(account) and name==foo")
    async with inventory_service.search_table(db, request) as response:
        result = [e async for e in response]
        assert result == expected
    # search in history data
    request = SearchRequest(query="is(account) and name==foo", history=HistorySearch(change=HistoryChange.node_created))
    async with inventory_service.search_table(db, request) as response:
        result = [e async for e in response]
        assert result == expected
    request = SearchRequest(query="is(account) and name==foo")
    async with inventory_service.search_table(db, request, "csv") as response:
        result = [e async for e in response]
    assert result == ["name,some_int", "a,1"]
    request = SearchRequest(
        query="is(account) and name==foo", sort=[SortOrder(path="/reported.name", direction="desc")]
    )
    async with inventory_service.search_table(db, request, "csv") as response:
        result = [e async for e in response]
    assert result == ["name,some_int", "a,1"]


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
    assert res["resource"] == azure_virtual_machine_resource_json
    assert len(res["resource"]["security"]["issues"]) == 1  # resource has one issue
    assert len(res["checks"]) == 1  # one failing check is loaded
    assert res["checks"][0]["id"] == res["resource"]["security"]["issues"][0]["check"]  # check id is the same


async def test_resource_neighborhood(
    inventory_service: InventoryService, mocked_answers: RequestHandlerMock, azure_virtual_machine_resource_json: Json
) -> None:
    async with inventory_service.neighborhood(db, NodeId("some_node_id")) as result:
        assert [a async for a in result] == neighborhood


@pytest.mark.asyncio
async def test_account_deleted(
    inventory_service: InventoryService,
    graph_db_access: GraphDatabaseAccess,
    request_handler_mock: RequestHandlerMock,
    inventory_requests: List[Request],
    user: User,
) -> None:
    async def inventory_call(request: Request) -> Response:
        if request.url.path == "/graph/fix/search/list":
            return nd_json_response([{"id": "123", "reported": {}}])
        elif request.url.path == "/graph/fix/node/123":
            return json_response({})
        raise ValueError(f"Unexpected request: {request.url}")

    request_handler_mock.append(inventory_call)
    message = CloudAccountDeleted(
        CloudNames.AWS, user.id, FixCloudAccountId(uuid4()), graph_db_access.workspace_id, CloudAccountId("123")
    )
    await inventory_service._process_account_deleted(message)
    assert len(inventory_requests) == 2


@pytest.mark.asyncio
async def test_workspace_created(
    inventory_service: InventoryService,
    graph_db_access: GraphDatabaseAccess,
    request_handler_mock: RequestHandlerMock,
    inventory_requests: List[Request],
    workspace: Workspace,
    user: User,
) -> None:
    async def inventory_call(request: Request) -> Response:
        content = request.content.decode("utf-8")
        if request.url.path == "/graph/fix":
            assert request.headers["FixGraphDbCreateDatabase"] == "true"
            return json_response({"id": "root", "reported": {"kind": "graph_root", "name": "root"}})
        elif request.url.path == "/config/fix.core":
            return json_response(json.loads(request.content))
        raise ValueError(f"Unexpected request: {request.url}: {content}")

    request_handler_mock.append(inventory_call)
    await inventory_service._process_workspace_created(
        WorkspaceCreated(
            workspace.id,
            workspace.name,
            workspace.slug,
            user.id,
        )
    )
    assert len(inventory_requests) == 2


@pytest.mark.asyncio
async def test_process_account_name(
    inventory_service: InventoryService,
    graph_db_access: GraphDatabaseAccess,
    request_handler_mock: RequestHandlerMock,
    inventory_requests: List[Request],
) -> None:
    async def inventory_call(request: Request) -> Response:
        if request.url.path == "/graph/fix/search/list":
            return nd_json_response([{"id": "123", "reported": {}}])
        elif request.url.path == "/graph/fix/node/123":
            return json_response({})
        raise ValueError(f"Unexpected request: {request.url}")

    request_handler_mock.append(inventory_call)
    message = CloudAccountNameChanged(
        FixCloudAccountId(uuid4()),
        graph_db_access.workspace_id,
        CloudName("aws"),
        CloudAccountId("123"),
        "configured",
        UserCloudAccountName("test"),
        "test",
    )
    inventory_service.update_name_again_after = timedelta(seconds=0.2)  # reapply the name change after 0.2 seconds
    await inventory_service._process_account_name_changed(message)
    assert len(inventory_requests) == 2
    # Directly after the change, we see 2 requests
    # Then after some time the name change is reapplied by the worker
    await eventually(lambda: len(inventory_requests) == 4, timeout=3)


@pytest.mark.asyncio
async def test_config(
    inventory_service: InventoryService, graph_db_access: GraphDatabaseAccess, mocked_answers: RequestHandlerMock
) -> None:
    await inventory_service.update_report_config(
        graph_db_access,
        ReportConfig(ignore_checks=["a", "b"], ignore_benchmarks=["b1"], override_values={"foo": "bla"}),
    )
    assert await inventory_service.report_config(graph_db_access) == ReportConfig(
        ignore_checks=["a", "b"], ignore_benchmarks=["b1"], override_values={"foo": "bla"}
    )


@pytest.mark.asyncio
async def test_retention_period(
    inventory_service: InventoryService,
    mocked_answers: RequestHandlerMock,
    workspace: Workspace,
) -> None:
    await inventory_service.change_db_retention_period(workspace.id, timedelta(days=10))
    await inventory_service._process_product_tier_changed(
        ProductTierChanged(workspace.id, UserId(uid()), ProductTier.Enterprise, True, True, ProductTier.Plus)
    )


@pytest.mark.asyncio
async def test_benchmarks(
    inventory_service: InventoryService,
    graph_db_access: GraphDatabaseAccess,
    mocked_answers: RequestHandlerMock,
    inventory_requests: List[Request],
) -> None:
    for _ in range(5):
        benchmarks = await inventory_service.benchmarks(graph_db_access)
        assert len(benchmarks) == 2
    assert len(inventory_requests) == 1  # only one request is made, 4 are served from cache


@pytest.mark.asyncio
async def test_checks(
    inventory_service: InventoryService,
    graph_db_access: GraphDatabaseAccess,
    mocked_answers: RequestHandlerMock,
    inventory_requests: List[Request],
) -> None:
    for _ in range(5):
        checks = await inventory_service.checks(graph_db_access)
        assert len(checks) == 1
    assert len(inventory_requests) == 1  # only one request is made, 4 are served from cache
