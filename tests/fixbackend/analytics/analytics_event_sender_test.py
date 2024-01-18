#  Copyright (c) 2024. Some Engineering
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
from typing import List, Tuple

from httpx import AsyncClient, Request, Response, MockTransport
from pytest import fixture

from fixbackend.analytics.analytics_event_sender import GoogleAnalyticsEventSender
from fixbackend.analytics.events import AEAwsAccountDegraded
from fixbackend.ids import UserId, WorkspaceId
from fixbackend.utils import uid, md5

user_id = UserId(uid())
workspace_id = WorkspaceId(uid())


@fixture
def google_analytics_event_sender() -> Tuple[GoogleAnalyticsEventSender, List[Request]]:
    request_list = []

    async def mock(request: Request) -> Response:
        request_list.append(request)
        return Response(204)

    client = AsyncClient(transport=MockTransport(mock))
    return GoogleAnalyticsEventSender(client, "test", "test"), request_list


async def test_send_events(google_analytics_event_sender: Tuple[GoogleAnalyticsEventSender, List[Request]]) -> None:
    sender, request_list = google_analytics_event_sender
    await sender.send(AEAwsAccountDegraded(user_id, workspace_id, "some_error"))
    await sender.send_events()
    assert len(request_list) == 1
    assert json.loads(request_list[0].content) == {
        "client_id": md5(user_id),
        "events": [
            {
                "name": "fix_aws_account_degraded",
                "params": {"error": "some_error", "workspace_id": str(workspace_id)},
            }
        ],
    }
