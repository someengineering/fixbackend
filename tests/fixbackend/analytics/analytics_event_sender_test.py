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

from fixcloudutils.util import uuid_str, utc
from httpx import AsyncClient, Request, Response, MockTransport
from pytest import fixture

from fixbackend.analytics.analytics_event_sender import GoogleAnalyticsEventSender
from fixbackend.analytics.events import (
    AEAccountDegraded,
)
from fixbackend.ids import UserId, WorkspaceId
from fixbackend.utils import uid, md5
from fixbackend.workspaces.repository import WorkspaceRepository

user_id = UserId(uid())
workspace_id = WorkspaceId(uid())


@fixture
def google_analytics_event_sender(
    workspace_repository: WorkspaceRepository,
) -> Tuple[GoogleAnalyticsEventSender, List[Request]]:
    request_list = []

    async def mock(request: Request) -> Response:
        request_list.append(request)
        return Response(204)

    client = AsyncClient(transport=MockTransport(mock))
    return GoogleAnalyticsEventSender(client, "test", "test", workspace_repository), request_list


async def test_send_events(google_analytics_event_sender: Tuple[GoogleAnalyticsEventSender, List[Request]]) -> None:
    sender, request_list = google_analytics_event_sender
    degraded = AEAccountDegraded(uuid_str(), utc(), user_id, workspace_id, "aws", "some_error")
    await sender.send(degraded)
    await sender.send_events()
    assert len(request_list) == 1
    assert json.loads(request_list[0].content) == {
        "client_id": md5(user_id),
        "events": [
            {
                "name": "fix_account_degraded",
                "params": {
                    "error": "some_error",
                    "cloud": "aws",
                    "workspace_id": str(workspace_id),
                    "id": degraded.id,
                    "created_at": degraded.created_at.isoformat(),
                },
            }
        ],
    }
