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

import pytest
from httpx import AsyncClient, Request, Response, HTTPError

from fixbackend.notification.model import FailingBenchmarkChecksDetected
from fixbackend.notification.pagerduty.pagerduty_notification import PagerDutyNotificationSender
from tests.fixbackend.conftest import RequestHandlerMock


@pytest.fixture
def pagerduty_notification(
    http_client: AsyncClient, request_handler_mock: RequestHandlerMock
) -> PagerDutyNotificationSender:
    async def handler(request: Request) -> Response:
        body = json.loads(request.content)
        rk = body["routing_key"]
        if "events.pagerduty.com" in request.url.host and rk == "ok":
            return Response(204)
        elif rk == "fail":
            return Response(500)
        else:
            return Response(404)

    request_handler_mock.append(handler)
    return PagerDutyNotificationSender(http_client)


async def test_pagerduty_notification(
    pagerduty_notification: PagerDutyNotificationSender,
    alert_failing_benchmark_checks_detected: FailingBenchmarkChecksDetected,
) -> None:
    alert = alert_failing_benchmark_checks_detected
    # evaluate message
    message = pagerduty_notification.vulnerable_resources_detected(alert, "ok")
    assert message["routing_key"] == "ok"
    # sending should not fail
    await pagerduty_notification.send_alert(alert, dict(integration_key="ok"))
    # 5xx should raise an error
    with pytest.raises(HTTPError):
        await pagerduty_notification.send_alert(alert, dict(integration_key="fail"))
    # 4xx is ignored
    await pagerduty_notification.send_alert(alert, dict(integration_key="wrong"))
