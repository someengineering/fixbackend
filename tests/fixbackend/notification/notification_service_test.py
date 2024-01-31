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
import json
from datetime import timedelta

import pytest
from fixcloudutils.redis.event_stream import MessageContext
from fixcloudutils.types import Json
from fixcloudutils.util import utc
from httpx import AsyncClient, Request, Response

from fixbackend.auth.user_repository import UserRepository
from fixbackend.domain_events.events import TenantAccountsCollected, CloudAccountCollectInfo
from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.ids import WorkspaceId, TaskId, FixCloudAccountId, CloudAccountId, NodeId, BenchmarkName
from fixbackend.notification.email.email_messages import SecurityScanFinished
from fixbackend.notification.model import (
    WorkspaceAlert,
    AlertingSetting,
    FailingBenchmarkChecksDetected,
    FailedBenchmarkCheck,
    VulnerableResource,
    AlertOnChannel,
)
from fixbackend.notification.notification_service import NotificationService
from fixbackend.utils import uid
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository
from tests.fixbackend.conftest import (
    InMemoryEmailSender,
    RequestHandlerMock,
    json_response,
    nd_json_response,
    RedisPubSubPublisherMock,
)
from tests.fixbackend.inventory.inventory_service_test import mocked_answers  # noqa: F401


@pytest.mark.asyncio
async def test_sent_to_workspace(
    notification_service: NotificationService,
    workspace: Workspace,
    workspace_repository: WorkspaceRepository,
    user_repository: UserRepository,
    email_sender: InMemoryEmailSender,
) -> None:
    for id in range(100):
        user_dict = {
            "email": f"user-{id}@bar.com",
            "hashed_password": "notreallyhashed",
            "is_verified": True,
        }
        user = await user_repository.create(user_dict)
        await workspace_repository.add_to_workspace(workspace.id, user.id)

    await notification_service.send_message_to_workspace(workspace_id=workspace.id, message=SecurityScanFinished())

    # emails must be sent in batches of no more than 50
    assert len(email_sender.call_args) == 3
    assert len(email_sender.call_args[0].to) == 50
    assert len(email_sender.call_args[1].to) == 50
    assert len(email_sender.call_args[2].to) == 1


@pytest.mark.asyncio
async def test_sent_email(
    notification_service: NotificationService,
    email_sender: InMemoryEmailSender,
) -> None:
    await notification_service.send_email(to="1", subject="2", text="3", html="4")

    assert len(email_sender.call_args) == 1
    args = email_sender.call_args[0]
    assert args.to == ["1"]
    assert args.subject == "2"
    assert args.text == "3"
    assert args.html == "4"


@pytest.mark.asyncio
async def test_sent_message(
    notification_service: NotificationService,
    email_sender: InMemoryEmailSender,
) -> None:
    message = SecurityScanFinished()
    await notification_service.send_message(to="1", message=message)

    assert len(email_sender.call_args) == 1
    args = email_sender.call_args[0]
    assert args.to == ["1"]
    assert args.subject == message.subject()
    assert args.text == message.text()
    assert args.html == message.html()


@pytest.mark.skip("Only for manual testing")
@pytest.mark.asyncio
async def test_example_alert(notification_service: NotificationService) -> None:
    # use real client
    notification_service.inventory_service.client.client = AsyncClient()
    now = utc()
    one_year_ago = now - timedelta(days=365)
    ws_id = WorkspaceId(uid())
    access = GraphDatabaseAccess(ws_id, "http://localhost:8529", "resoto", "", "resoto")
    result = await notification_service._load_alert(
        access, BenchmarkName("aws_cis_2_0"), [TaskId("my_manual_sync")], "high", one_year_ago, now
    )
    print(result)


@pytest.mark.asyncio
async def test_marshal_unmarshal_alerts() -> None:
    resource = VulnerableResource(NodeId("id"), "kind", "name", "cloud", "account", "region")
    alert = FailingBenchmarkChecksDetected(
        workspace_id=WorkspaceId(uid()),
        benchmark=BenchmarkName("aws_cis_2_0"),
        severity="high",
        failed_checks_count_total=123,
        examples=[FailedBenchmarkCheck("test", "Some title", "high", 23, [resource, resource])],
        link="https://foo.com",
    )
    on_channel = AlertOnChannel(alert, "email")
    js = on_channel.to_json()
    json.dumps(js)  # check that it is json serializable
    again = AlertOnChannel.from_json(js)
    assert again == on_channel


@pytest.mark.asyncio
async def test_send_alert(
    notification_service: NotificationService,
    graph_db_access: GraphDatabaseAccess,
    mocked_answers: RequestHandlerMock,  # noqa: F811
    example_check: Json,
    redis_publisher_mock: RedisPubSubPublisherMock,
) -> None:
    async def request_handler(request: Request) -> Response:
        if request.url == "https://discord.com/webhook_example":
            return Response(204)
        elif request.url.path == "/report/benchmarks":
            return json_response(["aws_cis_2_0"])
        elif request.url.path == "/report/checks":
            return json_response([example_check])
        elif request.url.path == "/graph/resoto/search/history/list":
            return nd_json_response(
                [dict(count=123, group=dict(check="aws_c1", severity="high", benchmark="aws_cis_2_0"))]
            )
        elif request.url.path == "/cli/execute":
            return nd_json_response(
                [
                    dict(
                        id="r1",
                        kind="aws_s3_bucket",
                        name="my_bucket",
                        cloud="aws",
                        account="123",
                        region="eu-central-1",
                        checks=["aws_c1"],
                    )
                ]
            )
        else:
            raise Exception(f"Unexpected request: {request.url}")

    # setup
    ws_id = graph_db_access.workspace_id
    mocked_answers.insert(0, request_handler)
    await notification_service.update_notification_provider_config(
        ws_id, "discord", "test", {"webhook_url": "https://discord.com/webhook_example"}
    )
    setting = AlertingSetting(severity="high", channels=["discord"])
    aws_cis_2_0 = BenchmarkName("aws_cis_2_0")
    await notification_service.update_alerting_for(WorkspaceAlert(workspace_id=ws_id, alerts={aws_cis_2_0: setting}))
    event = TenantAccountsCollected(
        graph_db_access.workspace_id,
        {FixCloudAccountId(uid()): CloudAccountCollectInfo(CloudAccountId("12345"), 123, 123, utc(), TaskId("1"))},
        None,
    )

    # create alerts
    await notification_service.alert_on_changed(event)

    # ensure that an alert was created
    assert len(redis_publisher_mock.messages) == 1
    kind, message, channel = redis_publisher_mock.last_message  # type: ignore
    assert kind == "vulnerable_resources_detected"
    on_channel = AlertOnChannel.from_json(message)
    assert on_channel.channel == "discord"
    assert isinstance(on_channel.alert, FailingBenchmarkChecksDetected)
    alert: FailingBenchmarkChecksDetected = on_channel.alert
    assert alert.severity == "high"
    assert len(alert.examples) == 1
    example = alert.examples[0]
    assert example.severity == "high"
    assert example.title == "Check S3 Account Level Public Access Block."
    assert example.failed_resources == 123
    assert len(example.examples) == 1
    resource = example.examples[0]
    assert resource.id == "r1"
    assert resource.kind == "aws_s3_bucket"
    assert resource.name == "my_bucket"

    # send alert
    await notification_service._send_alert(message, MessageContext("1", kind, "test", utc(), utc()))
