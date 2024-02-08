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
from httpx import AsyncClient, Request, Response, HTTPError

from fixbackend.notification.discord.discord_notification import DiscordNotificationSender
from fixbackend.notification.model import FailingBenchmarkChecksDetected
from tests.fixbackend.conftest import RequestHandlerMock


@pytest.fixture
def discord_notification(
    http_client: AsyncClient, request_handler_mock: RequestHandlerMock
) -> DiscordNotificationSender:
    async def handler(request: Request) -> Response:
        url = str(request.url)
        if "discord.com/my_webhook" in url:
            return Response(204)
        elif "discord.com/failure/5xx" in url:
            return Response(500)
        else:
            return Response(404)

    request_handler_mock.append(handler)
    return DiscordNotificationSender(http_client)


async def test_discord_notification(
    discord_notification: DiscordNotificationSender,
    alert_failing_benchmark_checks_detected: FailingBenchmarkChecksDetected,
) -> None:
    alert = alert_failing_benchmark_checks_detected
    # evaluate message
    message = discord_notification.vulnerable_resources_detected(alert)
    assert len(message["embeds"]) == 1
    # sending should not fail
    await discord_notification.send_alert(alert, dict(webhook_url="https://discord.com/my_webhook"))
    # 5xx should raise an error
    with pytest.raises(HTTPError):
        await discord_notification.send_alert(alert, dict(webhook_url="https://discord.com/failure/5xx"))
    # 4xx is ignored
    await discord_notification.send_alert(alert, dict(webhook_url="https://discord.com/does_not_exist"))
