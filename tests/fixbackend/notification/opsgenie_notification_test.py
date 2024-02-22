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
from fixbackend.notification.opsgenie.opsgenie_notification import OpsgenieNotificationSender
from tests.fixbackend.conftest import RequestHandlerMock


@pytest.fixture
def opsgenie_notification(
    http_client: AsyncClient, request_handler_mock: RequestHandlerMock
) -> OpsgenieNotificationSender:
    async def handler(request: Request) -> Response:
        auth = request.headers["Authorization"]
        if "api.opsgenie.com" in request.url.host and "ok" in auth:
            return Response(204)
        elif "fail" in auth:
            return Response(500)
        else:
            return Response(404)

    request_handler_mock.append(handler)
    return OpsgenieNotificationSender(http_client)


async def test_pagerduty_notification(
    opsgenie_notification: OpsgenieNotificationSender,
    alert_failing_benchmark_checks_detected: FailingBenchmarkChecksDetected,
) -> None:
    alert = alert_failing_benchmark_checks_detected
    # evaluate message
    message = opsgenie_notification.vulnerable_resources_detected(alert)
    assert message["priority"] == "P1"
    # sending should not fail
    await opsgenie_notification.send_alert(alert, dict(api_key="ok"))
    # 5xx should raise an error
    with pytest.raises(HTTPError):
        await opsgenie_notification.send_alert(alert, dict(api_key="fail"))
    # 4xx is ignored
    await opsgenie_notification.send_alert(alert, dict(api_key="wrong"))
