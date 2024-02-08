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

from fixbackend.notification.model import FailingBenchmarkChecksDetected
from fixbackend.notification.slack.slack_notification import SlackNotificationSender
from tests.fixbackend.conftest import RequestHandlerMock


@pytest.fixture
def slack_notification(http_client: AsyncClient, request_handler_mock: RequestHandlerMock) -> SlackNotificationSender:
    async def handler(request: Request) -> Response:
        url = str(request.url)
        if "slack.com/my_webhook" in url:
            return Response(204)
        elif "slack.com/failure/5xx" in url:
            return Response(500)
        else:
            return Response(404)

    request_handler_mock.append(handler)
    return SlackNotificationSender(http_client)


async def test_slack_notification(
    slack_notification: SlackNotificationSender, alert_failing_benchmark_checks_detected: FailingBenchmarkChecksDetected
) -> None:
    alert = alert_failing_benchmark_checks_detected
    # evaluate message
    message = slack_notification.vulnerable_resources_detected(alert_failing_benchmark_checks_detected)
    assert len(message["attachments"]) == 1
    # sending should not fail
    await slack_notification.send_alert(alert, dict(webhook_url="https://slack.com/my_webhook"))
    # 5xx should raise an error
    with pytest.raises(HTTPError):
        await slack_notification.send_alert(alert, dict(webhook_url="https://slack.com/failure/5xx"))
    # 4xx is ignored
    await slack_notification.send_alert(alert, dict(webhook_url="https://slack.com/does_not_exist"))
