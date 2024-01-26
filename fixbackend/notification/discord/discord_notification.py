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

from fixcloudutils.types import Json
from httpx import AsyncClient

from fixbackend.config import Config, get_config
from fixbackend.ids import WorkspaceId
from fixbackend.notification.service import (
    AlertSender,
    Alert,
    FailingBenchmarkChecksDetected,
    FailedBenchmarkCheck,
    VulnerableResource,
)
from fixbackend.utils import uid


class DiscordNotificationSender(AlertSender):
    def __init__(self, config: Config, http_client: AsyncClient) -> None:
        self.config = config
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
                        f"\n```\n{alert.failed_checks_count_total} issues require your attention.\n```\n\n"
                        f"These issues are in violation of the benchmark standards set in `{alert.benchmark}`. "
                        f"Your notification settings are configured to alert you for issues of severity {alert.severity}. "
                        "We recommend reviewing and addressing these issues promptly to ensure optimal performance and security compliance. "
                        "Please refer to our detailed report for more information and guidance on remediation steps.\n\n"
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

            await self.http_client.post(url, json=message)


# TODO: REMOVE ME!
if __name__ == "__main__":
    config = get_config()
    config.service_base_url = "https://app.dev.fixcloud.io"
    sender = DiscordNotificationSender(config, AsyncClient())
    resources = [VulnerableResource(f"t{a}", "aws_ec2_instance", f"test_{a}") for a in range(5)]
    a = sender.vulnerable_resources_detected(
        FailingBenchmarkChecksDetected(
            WorkspaceId(uid()),
            "aws_cis_2_0",
            "critical",
            23,
            [
                FailedBenchmarkCheck(
                    "snapshot_encrypted",
                    "Ensure that EBS Snapshots are both encrypted and not publicly accessible",
                    "critical",
                    23,
                    resources,
                ),
                FailedBenchmarkCheck(
                    "unused_elastic_ip",
                    "Ensure There are no Unassigned Elastic IPs in Your AWS Environment",
                    "critical",
                    12,
                    resources,
                ),
                FailedBenchmarkCheck(
                    "instance_in_vpc",
                    "Ensure All EC2 Instances Operate Within a VPC Instead of EC2-Classic",
                    "critical",
                    33,
                    resources,
                ),
                FailedBenchmarkCheck(
                    "internet_facing_with_instance_profile",
                    "Ensure No Internet Facing EC2 Instances with Instance Profiles Attached Exist",
                    "critical",
                    543,
                    resources,
                ),
                FailedBenchmarkCheck(
                    "old_instances",
                    "Ensure EC2 Instances Are Not Older Than Specific Days.",
                    "critical",
                    2,
                    resources,
                ),
            ],
            "https://app.dev.fixcloud.io",
        )
    )
    print(json.dumps(a, indent=2))
