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

import pytest
from fixcloudutils.types import Json
from fixcloudutils.util import utc
from httpx import Request, Response

from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.ids import WorkspaceId, CloudAccountId, NodeId
from fixbackend.inventory.inventory_client import InventoryClient
from fixbackend.inventory.schemas import CompletePathRequest, HistoryChange
from tests.fixbackend.conftest import RequestHandlerMock, nd_json_response, json_response

db_access = GraphDatabaseAccess(WorkspaceId(uuid.uuid1()), "server", "database", "username", "password")


@pytest.fixture
def mocked_inventory_client(
    inventory_client: InventoryClient,
    request_handler_mock: RequestHandlerMock,
    azure_virtual_machine_resource_json: Json,
    aws_ec2_model_json: Json,
) -> InventoryClient:
    async def mock(request: Request) -> Response:
        content = request.content.decode("utf-8")

        if request.url.path == "/cli/execute" and content == "json [1,2,3]":
            return Response(200, content=b'"1"\n"2"\n"3"\n', headers={"content-type": "application/x-ndjson"})
        elif request.url.path == "/report/benchmarks":
            return json_response(
                [{"clouds": ["aws"], "description": "Test AWS", "framework": "CIS", "id": "aws_test", "report_checks": [{"id": "aws_c1", "severity": "high"}, {"id": "aws_c2", "severity": "critical"}], "title": "AWS Test", "version": "0.1"},  # fmt: skip
                 {"clouds": ["gcp"], "description": "Test GCP", "framework": "CIS", "id": "gcp_test", "report_checks": [{"id": "gcp_c1", "severity": "low"}, {"id": "gcp_c2", "severity": "medium"}], "title": "GCP Test", "version": "0.2"}]  # fmt: skip
            )
        elif request.url.path == "/graph/resoto/search/list":
            return nd_json_response([dict(id="123", reported={})])
        elif request.url.path == "/graph/resoto/search/history/list":
            return nd_json_response([dict(id="123", reported={})])
        elif request.method == "DELETE" and request.url.path == "/graph/resoto/node/123":
            return nd_json_response([dict(id="123", reported={})])
        elif request.url.path == "/graph/resoto/property/attributes":
            return nd_json_response(["prop_a", "prop_b", "prop_c"])
        elif request.url.path == "/graph/resoto/property/values":
            return nd_json_response(["val_a", "val_b", "val_c"])
        elif request.url.path == "/graph/resoto/property/path/complete":
            cpl = CompletePathRequest.model_validate_json(request.content)
            assert cpl == CompletePathRequest(path="test", prop="bla", fuzzy=True, limit=1, skip=2, kinds=["a"])
            return json_response({"a": "string", "b": "int32", "c": "boolean"}, {"Total-Count": "12"})
        elif request.url.path == "/graph/resoto/model":
            return json_response([aws_ec2_model_json])
        elif request.method == "GET" and request.url.path == "/graph/resoto/node/some_node_id":
            return json_response(azure_virtual_machine_resource_json)
        elif request.method == "PATCH" and request.url.path == "/graph/resoto/node/some_node_id":
            js = json.loads(request.content)
            azure_virtual_machine_resource_json["reported"] = azure_virtual_machine_resource_json["reported"] | js
            return json_response(azure_virtual_machine_resource_json)
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

        else:
            raise AttributeError(f"Unexpected request: {request.method} {request.url.path} with content {content}")

    request_handler_mock.append(mock)
    return inventory_client


async def test_execute_single(mocked_inventory_client: InventoryClient) -> None:
    assert [a async for a in await mocked_inventory_client.execute_single(db_access, "json [1,2,3]")] == ["1", "2", "3"]


async def test_report_benchmarks(mocked_inventory_client: InventoryClient) -> None:
    result = await mocked_inventory_client.benchmarks(db_access, short=True, with_checks=True)
    assert len(result) == 2
    for entry in result:
        for prop in ["id", "title", "framework", "version", "clouds", "description", "report_checks"]:
            assert prop in entry


async def test_deletion(mocked_inventory_client: InventoryClient) -> None:
    await mocked_inventory_client.delete_account(db_access, cloud="aws", account_id=CloudAccountId("test"))


async def test_possible_values(mocked_inventory_client: InventoryClient) -> None:
    keys = await mocked_inventory_client.possible_values(
        db_access, query="is(account)", prop_or_predicate="tags", detail="attributes"
    )
    assert [e async for e in keys] == ["prop_a", "prop_b", "prop_c"]
    vals = await mocked_inventory_client.possible_values(db_access, query="is(account)", prop_or_predicate="id")
    assert [e async for e in vals] == ["val_a", "val_b", "val_c"]


async def test_model(mocked_inventory_client: InventoryClient, aws_ec2_model_json: Json) -> None:
    result = await mocked_inventory_client.model(db_access, kind=["aws_ec2_instance"], result_format="simple")
    assert result == [aws_ec2_model_json]


async def test_resource(mocked_inventory_client: InventoryClient, azure_virtual_machine_resource_json: Json) -> None:
    result = await mocked_inventory_client.resource(db_access, id=NodeId("some_node_id"))
    assert result == azure_virtual_machine_resource_json


async def test_complete(mocked_inventory_client: InventoryClient, azure_virtual_machine_resource_json: Json) -> None:
    request = CompletePathRequest(path="test", prop="bla", fuzzy=True, limit=1, skip=2, kinds=["a"])
    count, result = await mocked_inventory_client.complete_property_path(db_access, request=request)
    assert count == 12
    assert result == {"a": "string", "b": "int32", "c": "boolean"}


async def test_node_update(mocked_inventory_client: InventoryClient) -> None:
    result = await mocked_inventory_client.update_node(db_access, NodeId("some_node_id"), {"foo": "4"})
    assert result["reported"]["foo"] == "4"
    result = await mocked_inventory_client.update_node(db_access, NodeId("some_node_id"), {"foo": "1234"})
    assert result["reported"]["foo"] == "1234"


async def test_timeseries(mocked_inventory_client: InventoryClient) -> None:
    result = await mocked_inventory_client.timeseries(db_access, name="infected_resources", start=utc(), end=utc())
    result_list = [e async for e in result]
    assert len(result_list) == 8


async def test_search_history(mocked_inventory_client: InventoryClient) -> None:
    response = await mocked_inventory_client.search_history(
        db_access, "is(account)", before=utc(), after=utc(), change=HistoryChange.node_vulnerable
    )
    result = [n async for n in response]
    assert len(result) == 1
