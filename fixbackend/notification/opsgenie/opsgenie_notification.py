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
from httpx import AsyncClient

from fixbackend.httpx_extensions import HttpXResponse, ServerError, SuccessResponse
from fixbackend.notification.model import (
    AlertSender,
    Alert,
    FailingBenchmarkChecksDetected,
)

log = logging.getLogger(__name__)

SeverityToOpsgeniePriority = defaultdict(
    lambda: "P3",
    {"critical": "P1", "high": "P2", "medium": "P3", "low": "P4", "info": "P5"},
)


class OpsgenieNotificationSender(AlertSender):
    def __init__(self, http_client: AsyncClient) -> None:
        self.http_client = http_client

    def vulnerable_resources_detected(self, alert: FailingBenchmarkChecksDetected) -> Json:
        return {
            "message": f"{alert.failed_checks_count_total} new issues detected in your infrastructure for benchmark {alert.benchmark}",
            "alias": alert.id,
            "description": f"See all details here: {alert.ui_link}",
            "tags": ["Security", "Fix"],
            "details": {
                f"{fail.emoji()} {fail.severity.capitalize()}: {fail.title}": f"{fail.failed_resources} additional resources detected, that are failing this check."  # noqa: E501
                for num, fail in enumerate(alert.examples)
            },
            "priority": SeverityToOpsgeniePriority[alert.severity],
            "source": "FIX",
        }

    async def send_alert(self, alert: Alert, config: Json) -> None:
        if api_key := config.get("api_key"):
            match alert:
                case FailingBenchmarkChecksDetected() as vrd:
                    message = self.vulnerable_resources_detected(vrd)
                case _:
                    raise ValueError(f"Unknown alert: {alert}")

            match HttpXResponse.read(
                await self.http_client.post(
                    "https://api.opsgenie.com/v2/alerts", headers={"Authorization": f"GenieKey {api_key}"}, json=message
                )
            ):
                case SuccessResponse():
                    log.info("Send opsgenie alert notification.")
                case ServerError(response):
                    log.info(f"Could not send opsgenie notification due to server error: {response.text}. Retry.")
                    response.raise_for_status()  # raise exception and trigger retry
                case error:
                    log.info(f"Could not send opsgenie notification due to error: {error}. Give up.")
