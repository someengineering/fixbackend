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
import pickle
import uuid
from typing import Any, Sequence, Mapping

import pytest
from redis.asyncio import Redis

from fixbackend.collect.collect_queue import (
    RedisCollectQueue,
    JobAlreadyEnqueued,
    AwsAccountInformation,
    GcpProjectInformation,
    AzureSubscriptionInformation,
)
from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.ids import WorkspaceId, CloudAccountId, AwsARN, ExternalId, CloudAccountName
from uuid import uuid4


@pytest.fixture
def graph_db_access() -> GraphDatabaseAccess:
    return GraphDatabaseAccess(
        workspace_id=WorkspaceId(uuid.uuid4()),
        server="http://localhost:8529",
        username="test",
        password="test",
        database="test",
    )


@pytest.mark.asyncio
async def test_redis_collect_queue(
    arq_redis: Redis, collect_queue: RedisCollectQueue, graph_db_access: GraphDatabaseAccess
) -> None:
    # assert no keys in redis
    assert set(await arq_redis.keys()) == set()
    # enqueue new job
    aws_account = AwsAccountInformation(
        CloudAccountId("123"), CloudAccountName("test"), AwsARN("arn"), ExternalId(uuid4())
    )
    await collect_queue.enqueue(graph_db_access, aws_account, job_id="test")
    assert set(await arq_redis.keys()) == {b"arq:queue", b"arq:job:test"}
    # enqueue again will fail
    with pytest.raises(JobAlreadyEnqueued):
        await collect_queue.enqueue(graph_db_access, aws_account, job_id="test")

    # make sure the job is valid json
    def assert_json(obj: Any) -> None:
        if obj is None or isinstance(obj, (str, int, bool)):
            pass
        elif isinstance(obj, Sequence):
            for item in obj:
                assert_json(item)
        elif isinstance(obj, Mapping):
            for k, v in obj.items():
                assert isinstance(k, str)
                assert_json(v)
        else:
            raise TypeError(f"Unexpected type {type(obj)}")

    assert_json(pickle.loads(await arq_redis.get("arq:job:test")))


def test_aws_account_info_json() -> None:
    external_id = ExternalId(uuid4())
    aws_account_info = AwsAccountInformation(
        aws_account_id=CloudAccountId("123456789012"),
        aws_account_name=CloudAccountName("test"),
        aws_role_arn=AwsARN("arn:aws:iam::123456789012:role/test"),
        external_id=external_id,
    )
    assert aws_account_info.to_json() == {
        "kind": "aws_account_information",
        "aws_account_id": "123456789012",
        "aws_account_name": "test",
        "aws_role_arn": "arn:aws:iam::123456789012:role/test",
        "external_id": str(external_id),
    }


def test_gcp_project_info_json() -> None:
    project = GcpProjectInformation(
        gcp_project_id=CloudAccountId("test"),
        google_application_credentials={"test": "test"},
    )
    assert project.to_json() == {
        "kind": "gcp_project_information",
        "gcp_project_id": "test",
        "google_application_credentials": {"test": "test"},
    }


def test_azure_subscription_json() -> None:
    subscription = AzureSubscriptionInformation(
        azure_subscription_id=CloudAccountId("test"),
        tenant_id="test1",
        client_id="test2",
        client_secret="test3",
    )
    assert subscription.to_json() == {
        "kind": "azure_subscription_information",
        "azure_subscription_id": "test",
        "tenant_id": "test1",
        "client_id": "test2",
        "client_secret": "test3",
    }
