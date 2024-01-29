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


class DiscordNotificationSender(AlertSender):
    def __init__(self, cfg: Config, http_client: AsyncClient) -> None:
        self.config = cfg
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
                        "url": "https://fix.tt",
                        "icon_url": "https://cdn.some.engineering/assets/fix-logos/fix-logo-256.png",
                    },
                    "url": self.config.service_base_url,  # TODO: add workspace id
                    "description": (
                        f"We have completed a comprehensive scan of your infrastructure."
                        f"\n```\n{alert.failed_checks_count_total} issues require your attention.\n```\n"
                        f"These issues are in violation of the benchmark standards set in `{alert.benchmark}`.\n"
                        f"Here is a {note}list of failing checks:\n\n"
                    ),
                    "fields": [
                        {
                            "name": f"**{vr.severity.capitalize()}**: *{vr.title}*",
                            "value": f"{vr.failed_resources} additional resources detected.\nExamples: "
                            + ", ".join(
                                f"[{rr.name}]({rr.ui_link(self.config.service_base_url)})" for rr in vr.examples
                            ),
                        }
                        for vr in alert.examples
                    ]
                    + exhausted
                    + [{"name": "See the full list of failing resources", "value": f"[View in FIX]({alert.link})"}],
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

            log.info(f"Send discord notification for workspace {alert.workspace_id}")
            response = await self.http_client.post(url, json=message)
            response.raise_for_status()
