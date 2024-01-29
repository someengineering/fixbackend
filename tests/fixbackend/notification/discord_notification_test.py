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
import pytest
from httpx import AsyncClient, Request, Response

from fixbackend.config import Config
from fixbackend.ids import WorkspaceId
from fixbackend.notification.discord.discord_notification import DiscordNotificationSender
from fixbackend.notification.model import FailingBenchmarkChecksDetected, FailedBenchmarkCheck, VulnerableResource
from fixbackend.utils import uid
from tests.fixbackend.conftest import RequestHandlerMock


@pytest.fixture
def discord_notification(
    default_config: Config, http_client: AsyncClient, request_handler_mock: RequestHandlerMock
) -> DiscordNotificationSender:
    async def handler(request: Request) -> Response:
        if "discord.com" in request.url.host:
            return Response(204)
        else:
            return Response(404)

    request_handler_mock.append(handler)
    return DiscordNotificationSender(default_config, http_client)


def test_discord_notification(discord_notification: DiscordNotificationSender) -> None:
    alert = FailingBenchmarkChecksDetected(
        WorkspaceId(uid()),
        "test",
        "critical",
        23,
        [
            FailedBenchmarkCheck(
                "example_check",
                "Title of check",
                "critical",
                12,
                [VulnerableResource("id1", "test_resource", "some_name")],
            )
        ],
        "https://fix.tt/",
    )
    # sending should not fail
    assert discord_notification.send_alert(alert, dict(webhook_url="http://discord.com/my_webhook"))
    # evaluate message
    message = discord_notification.vulnerable_resources_detected(alert)
    assert len(message["embeds"]) == 1
