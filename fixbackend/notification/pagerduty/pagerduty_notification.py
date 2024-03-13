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
import logging
from collections import defaultdict

from fixcloudutils.types import Json
from fixcloudutils.util import utc_str
from httpx import AsyncClient

from fixbackend.httpx_extensions import HttpXResponse, ServerError, SuccessResponse
from fixbackend.notification.model import (
    AlertSender,
    Alert,
    FailingBenchmarkChecksDetected,
)

log = logging.getLogger(__name__)

SeverityToPagerDutySeverity = defaultdict(
    lambda: "error",
    {
        "critical": "critical",
        "high": "error",
        "medium": "warning",
        "low": "info",
        "info": "info",
    },
)


class PagerDutyNotificationSender(AlertSender):
    def __init__(self, http_client: AsyncClient) -> None:
        self.http_client = http_client

    def vulnerable_resources_detected(self, alert: FailingBenchmarkChecksDetected, integration_key: str) -> Json:
        return {
            "routing_key": integration_key,
            "dedup_key": alert.id,
            "event_action": "trigger",
            "links": [{"href": alert.ui_link, "text": "See all failed resources in FIX"}],
            "images": [
                {
                    "src": "https://cdn.fix.security/assets/fix-logos/fix-logo-192.png",
                    "href": alert.ui_link,
                    "alt": "Fix Home Page",
                }
            ],
            "payload": {
                "summary": f"{alert.failed_checks_count_total} new issues detected in your infrastructure for benchmark {alert.benchmark}",
                "severity": SeverityToPagerDutySeverity[alert.severity],
                "source": "FIX",
                "timestamp": utc_str(),
                "component": "FIX",
                "group": "Benchmark",
                "class": alert.benchmark,
                "custom_details": {
                    f"{fail.emoji()} {fail.severity.capitalize()}: {fail.title}": f"{fail.failed_resources} additional resources detected, that are failing this check."  # noqa: E501
                    for num, fail in enumerate(alert.examples)
                },
            },
        }

    async def send_alert(self, alert: Alert, config: Json) -> None:
        if integration_key := config.get("integration_key"):
            match alert:
                case FailingBenchmarkChecksDetected() as vrd:
                    message = self.vulnerable_resources_detected(vrd, integration_key)
                case _:
                    raise ValueError(f"Unknown alert: {alert}")

            match HttpXResponse.read(
                await self.http_client.post("https://events.pagerduty.com/v2/enqueue", json=message)
            ):
                case SuccessResponse():
                    log.info("Send pagerduty alert notification.")
                case ServerError(response):
                    log.info(f"Could not send pagerduty notification due to server error: {response.text}. Retry.")
                    response.raise_for_status()  # raise exception and trigger retry
                case error:
                    log.info(f"Could not send pagerduty notification due to error: {error}. Give up.")
