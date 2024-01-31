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

from fixbackend.config import Config
from fixbackend.notification.model import (
    AlertSender,
    Alert,
    FailingBenchmarkChecksDetected,
)

log = logging.getLogger(__name__)


class TeamsNotificationSender(AlertSender):
    def __init__(self, cfg: Config, http_client: AsyncClient) -> None:
        self.config = cfg
        self.http_client = http_client

    def vulnerable_resources_detected(self, alert: FailingBenchmarkChecksDetected) -> Json:
        not_ex = [
            {
                "name": "",
                "value": "Please note that this list represents only a portion of the total issues found. "
                "You can review the full report with all affected resources using below button.\n",
            }
        ]
        exhausted, note = (
            (not_ex, "non exhaustive ") if len(alert.examples) < alert.failed_checks_count_total else ([], "")
        )

        return {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": "16744272",
            "summary": "New issues Detected in your Infrastructure",
            "sections": [
                {
                    "activityTitle": "**New issues Detected in your Infrastructure!**",
                    "activitySubtitle": f"{alert.emoji()} **{alert.severity.capitalize()}**: {alert.failed_checks_count_total} new issues",  # noqa: E501
                    "activityImage": "https://cdn.some.engineering/assets/fix-logos/fix-logo-256.png",
                    "facts": [
                        {
                            "name": failed.emoji(),
                            "value": f"***{failed.severity.capitalize()}*** **{failed.title}**\n\n"
                            f"*{failed.failed_resources} additional resources detected.*\n\n"
                            f"Examples: "
                            + ", ".join(
                                f"[{vr.name}]({vr.ui_link(self.config.service_base_url)})" for vr in failed.examples
                            ),
                        }
                        for failed in alert.examples
                    ]
                    + exhausted,
                    "markdown": True,
                }
            ],
            "potentialAction": [
                {
                    "@type": "OpenUri",
                    "name": "View in FIX",
                    "targets": [{"os": "default", "uri": alert.link}],
                }
            ],
        }

    async def send_alert(self, alert: Alert, config: Json) -> None:
        if url := config.get("webhook_url"):
            match alert:
                case FailingBenchmarkChecksDetected() as vrd:
                    message = self.vulnerable_resources_detected(vrd)
                case _:
                    raise ValueError(f"Unknown alert: {alert}")

            log.info(f"Send teams notification for workspace {alert.workspace_id}")
            response = await self.http_client.post(url, json=message)
            response.raise_for_status()
