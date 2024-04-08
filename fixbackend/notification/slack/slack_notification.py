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

from fixbackend.httpx_extensions import HttpXResponse, SuccessResponse, ServerError
from fixbackend.notification.model import (
    AlertSender,
    Alert,
    FailingBenchmarkChecksDetected,
)

log = logging.getLogger(__name__)


class SlackNotificationSender(AlertSender):
    def __init__(self, http_client: AsyncClient) -> None:
        self.http_client = http_client

    def vulnerable_resources_detected(self, alert: FailingBenchmarkChecksDetected) -> Json:
        not_ex = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Note: Please note that this list represents only a portion of the total issues found. "
                    "You can review the full report with all affected resources using below link.\n",
                },
            },
        ]
        exhausted, note = (
            (not_ex, "non exhaustive ") if len(alert.examples) < alert.failed_checks_count_total else ([], "")
        )

        return {
            "attachments": [
                {
                    "color": "#FF7F50",
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": f"{alert.severity.capitalize()}: New issues Detected in your Infrastructure!",
                            },
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "We have completed a comprehensive scan of your infrastructure. \n"
                                f"```\n{alert.failed_checks_count_total} issues require your attention.\n```\n"
                                f"These issues are in violation of the benchmark standards set in `{alert.benchmark}`."
                                f"\nHere is a {note} list of failing checks:\n\n",
                            },
                            "accessory": {
                                "type": "image",
                                "image_url": "https://cdn.fix.security/assets/fix-logos/fix-logo-256.png",
                                "alt_text": "Fix",
                            },
                        },
                    ]
                    + [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"{vr.emoji()} *{vr.severity}*: {vr.title}\n"
                                f"{vr.failed_resources} additional resources detected.\n"
                                f"Examples: " + ", ".join(f"<{ex.ui_link}|{ex.name}>" for ex in vr.examples),
                            },
                        }
                        for vr in alert.examples
                    ]
                    + exhausted
                    + [
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "image",
                                    "image_url": "https://cdn.fix.security/assets/fix-logos/fix-logo-256.png",
                                    "alt_text": "Fix logo",
                                },
                                {
                                    "type": "mrkdwn",
                                    "text": f"See the full list of failing resources <{alert.ui_link}|View In Fix>",
                                },
                            ],
                        },
                    ],
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
                    log.info("Send slack alert notification")
                case ServerError(response):
                    log.info(f"Could not send slack notification due to server error: {response.text}. Retry.")
                    response.raise_for_status()  # raise exception and trigger retry
                case error:
                    log.info(f"Could not send slack notification due to error: {error}. Give up.")
