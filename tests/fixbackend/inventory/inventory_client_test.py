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
from httpx import Request, Response

from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.ids import WorkspaceId, CloudAccountId
from fixbackend.inventory.inventory_client import InventoryClient
from tests.fixbackend.conftest import InventoryMock, nd_json_response

db_access = GraphDatabaseAccess(WorkspaceId(uuid.uuid1()), "server", "database", "username", "password")

aws_ec2_model_simplified = {
    "type": "object",
    "fqn": "aws_ec2_instance",
    "bases": ["aws_resource", "instance", "resource"],
    "allow_unknown_props": False,
    "predecessor_kinds": {"default": ["aws_elb"], "delete": []},
    "successor_kinds": {"default": ["aws_ec2_volume"], "delete": []},
    "aggregate_root": True,
    "metadata": {"icon": "instance", "group": "compute"},
    "properties": {"id": {"kind": {"type": "simple", "fqn": "string"}, "required": False}},
}


@pytest.fixture
def mocked_inventory_client(inventory_client: InventoryClient, inventory_mock: InventoryMock) -> InventoryClient:
    async def mock(request: Request) -> Response:
        content = request.content.decode("utf-8")
        if request.url.path == "/cli/execute" and content == "json [1,2,3]":
            return Response(200, content=b'"1"\n"2"\n"3"\n', headers={"content-type": "application/x-ndjson"})
        elif request.url.path == "/report/benchmarks":
            benchmarks = [
                {"clouds": ["aws"], "description": "Test AWS", "framework": "CIS", "id": "aws_test", "report_checks": [{"id": "aws_c1", "severity": "high"}, {"id": "aws_c2", "severity": "critical"}], "title": "AWS Test", "version": "0.1"},  # fmt: skip
                {"clouds": ["gcp"], "description": "Test GCP", "framework": "CIS", "id": "gcp_test", "report_checks": [{"id": "gcp_c1", "severity": "low"}, {"id": "gcp_c2", "severity": "medium"}], "title": "GCP Test", "version": "0.2"},  # fmt: skip
            ]
            return Response(
                200, content=json.dumps(benchmarks).encode("utf-8"), headers={"content-type": "application/json"}
            )

        elif request.url.path == "/graph/resoto/search/list":
            return nd_json_response([dict(id="123", reported={})])
        elif request.method == "DELETE" and request.url.path == "/graph/resoto/node/123":
            return nd_json_response([dict(id="123", reported={})])
        elif request.url.path == "/graph/resoto/property/attributes":
            return nd_json_response(["prop_a", "prop_b", "prop_c"])
        elif request.url.path == "/graph/resoto/property/values":
            return nd_json_response(["val_a", "val_b", "val_c"])
        elif request.url.path == "/graph/resoto/model":
            return Response(
                200,
                content=json.dumps([aws_ec2_model_simplified]).encode("utf-8"),
                headers={"content-type": "application/json"},
            )
        else:
            raise AttributeError(f"Unexpected request: {request.method} {request.url.path} with content {content}")

    inventory_mock.append(mock)
    return inventory_client


async def test_execute_single(mocked_inventory_client: InventoryClient) -> None:
    assert [a async for a in mocked_inventory_client.execute_single(db_access, "json [1,2,3]")] == ["1", "2", "3"]


async def test_report_benchmarks(mocked_inventory_client: InventoryClient) -> None:
    result = await mocked_inventory_client.benchmarks(db_access, short=True, with_checks=True)
    assert len(result) == 2
    for entry in result:
        for prop in ["id", "title", "framework", "version", "clouds", "description", "report_checks"]:
            assert prop in entry


async def test_deletion(mocked_inventory_client: InventoryClient) -> None:
    await mocked_inventory_client.delete_account(db_access, cloud="aws", account_id=CloudAccountId("test"))


async def test_possible_values(mocked_inventory_client: InventoryClient) -> None:
    keys = mocked_inventory_client.possible_values(
        db_access, query="is(account)", prop_or_predicate="tags", detail="attributes"
    )
    assert [e async for e in keys] == ["prop_a", "prop_b", "prop_c"]
    vals = mocked_inventory_client.possible_values(db_access, query="is(account)", prop_or_predicate="id")
    assert [e async for e in vals] == ["val_a", "val_b", "val_c"]


async def test_model(mocked_inventory_client: InventoryClient) -> None:
    result = await mocked_inventory_client.model(db_access, kind=["aws_ec2_instance"], result_format="simple")
    assert result == [aws_ec2_model_simplified]
