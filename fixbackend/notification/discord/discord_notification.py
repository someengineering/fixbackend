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

from fixcloudutils.types import Json
from httpx import AsyncClient

from fixbackend.httpx_extensions import HttpXResponse, ServerError, SuccessResponse
from fixbackend.notification.model import (
    AlertSender,
    Alert,
    FailingBenchmarkChecksDetected,
)

log = logging.getLogger(__name__)


class DiscordNotificationSender(AlertSender):
    def __init__(self, http_client: AsyncClient) -> None:
        self.http_client = http_client

    def vulnerable_resources_detected(self, alert: FailingBenchmarkChecksDetected) -> Json:
        not_ex = [
            {
                "name": "Note",
                "value": "Please note that this list represents only a portion of the total issues found. "
                "You can review the full report with all affected resources using below link.\n",
            }
        ]
        exhausted, note = (
            (not_ex, "non exhaustive ") if len(alert.examples) < alert.failed_checks_count_total else ([], "")
        )

        return {
            "embeds": [
                {
                    "title": f"{alert.severity.capitalize()}: New issues Detected in your Infrastructure!",
                    "author": {
                        "name": "FIX",
                        "url": "https://fix.security",
                        "icon_url": "https://cdn.fix.security/assets/fix-logos/fix-logo-256.png",
                    },
                    "url": alert.ui_link,
                    "description": (
                        f"We have completed a comprehensive scan of your infrastructure.\n"
                        f"```\n{alert.failed_checks_count_total} issues require your attention.\n```\n"
                        f"These issues are in violation of the benchmark standards set in `{alert.benchmark}`.\n"
                        f"Here is a {note}list of failing checks:\n\n"
                    ),
                    "fields": [
                        {
                            "name": f"{vr.emoji()} **{vr.severity.capitalize()}**: *{vr.title}*",
                            "value": f"{vr.failed_resources} additional resources detected.\nExamples: "
                            + ", ".join(f"[{rr.name}]({rr.ui_link})" for rr in vr.examples),
                        }
                        for vr in alert.examples
                    ]
                    + exhausted
                    + [{"name": "See the full list of failing resources", "value": f"[View in FIX]({alert.ui_link})"}],
                    "color": 16744272,
                }
            ]
        }

    async def send_alert(self, alert: Alert, config: Json) -> None:
        if url := config.get("webhook_url"):
            match alert:
                case FailingBenchmarkChecksDetected() as vrd:
                    message = self.vulnerable_resources_detected(vrd)
                case _:
                    raise ValueError(f"Unknown alert: {alert}")

            match HttpXResponse.read(await self.http_client.post(url, json=message)):
                case SuccessResponse():
                    log.info("Send discord alert notification.")
                case ServerError(response):
                    log.info(f"Could not send discord notification due to server error: {response.text}. Retry.")
                    response.raise_for_status()  # raise exception and trigger retry
                case error:
                    log.info(f"Could not send discord notification due to error: {error}. Give up.")
