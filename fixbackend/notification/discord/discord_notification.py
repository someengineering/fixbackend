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
from uuid import UUID

from fixcloudutils.types import Json
from httpx import AsyncClient

from fixbackend.config import Config, get_config
from fixbackend.ids import WorkspaceId
from fixbackend.notification.notification_service import (
    AlertSender,
    Alert,
    FailingBenchmarkChecksDetected,
    FailedBenchmarkCheck,
    VulnerableResource,
)


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

            await self.http_client.post(url, json=message)


# TODO: REMOVE ME!
if __name__ == "__main__":
    config = get_config()
    config.service_base_url = "https://app.dev.fixcloud.io"
    sender = DiscordNotificationSender(config, AsyncClient())
    resources = [VulnerableResource(f"t{a}", "aws_ec2_instance", f"test_{a}") for a in range(5)]
    real = FailingBenchmarkChecksDetected(
        workspace_id=WorkspaceId(UUID("9a06566c-43db-4a3d-bfbe-bf18225e346e")),
        benchmark="aws_cis_2_0",
        severity="high",
        failed_checks_count_total=6,
        examples=[
            FailedBenchmarkCheck(
                check_id="aws_ec2_allow_ingress_any_port_ipv4",
                title="Ensure No Network ACLs Allow Ingress from 0.0.0.0/0 to Any Port.",
                severity="high",
                failed_resources=9,
                examples=[
                    VulnerableResource(
                        id="n13tgNYvbBN-zM03h4CzCg",
                        kind="aws_ec2_network_acl",
                        name="acl-0412d0e5cb5ba0515",
                        cloud="aws",
                        account="someengineering-development",
                        region="eu-central-1",
                        zone=None,
                    ),
                    VulnerableResource(
                        id="SvSHgLtHmgdnV6XpMY_Ksg",
                        kind="aws_ec2_network_acl",
                        name="acl-0810e5746d6988e77",
                        cloud="aws",
                        account="someengineering-development",
                        region="us-east-1",
                        zone=None,
                    ),
                    VulnerableResource(
                        id="8WEnqXUiBl39JeQiLmHpRw",
                        kind="aws_ec2_network_acl",
                        name="acl-0854a97eb614d5ef2",
                        cloud="aws",
                        account="someengineering-development",
                        region="us-east-1",
                        zone=None,
                    ),
                ],
            ),
            FailedBenchmarkCheck(
                check_id="aws_ec2_allow_ingress_ssh_port_22_ipv4",
                title="Ensure Network ACLs Do Not Allow Ingress from 0.0.0.0/0 to SSH Port 22",
                severity="high",
                failed_resources=9,
                examples=[
                    VulnerableResource(
                        id="n13tgNYvbBN-zM03h4CzCg",
                        kind="aws_ec2_network_acl",
                        name="acl-0412d0e5cb5ba0515",
                        cloud="aws",
                        account="someengineering-development",
                        region="eu-central-1",
                        zone=None,
                    ),
                    VulnerableResource(
                        id="SvSHgLtHmgdnV6XpMY_Ksg",
                        kind="aws_ec2_network_acl",
                        name="acl-0810e5746d6988e77",
                        cloud="aws",
                        account="someengineering-development",
                        region="us-east-1",
                        zone=None,
                    ),
                    VulnerableResource(
                        id="8WEnqXUiBl39JeQiLmHpRw",
                        kind="aws_ec2_network_acl",
                        name="acl-0854a97eb614d5ef2",
                        cloud="aws",
                        account="someengineering-development",
                        region="us-east-1",
                        zone=None,
                    ),
                ],
            ),
            FailedBenchmarkCheck(
                check_id="aws_ec2_allow_ingress_rdp_port_3389_ipv4",
                title="Ensure that Network ACLs do not allow ingress from 0.0.0.0/0 to Microsoft RDP port 3389",
                severity="high",
                failed_resources=9,
                examples=[
                    VulnerableResource(
                        id="n13tgNYvbBN-zM03h4CzCg",
                        kind="aws_ec2_network_acl",
                        name="acl-0412d0e5cb5ba0515",
                        cloud="aws",
                        account="someengineering-development",
                        region="eu-central-1",
                        zone=None,
                    ),
                    VulnerableResource(
                        id="SvSHgLtHmgdnV6XpMY_Ksg",
                        kind="aws_ec2_network_acl",
                        name="acl-0810e5746d6988e77",
                        cloud="aws",
                        account="someengineering-development",
                        region="us-east-1",
                        zone=None,
                    ),
                    VulnerableResource(
                        id="8WEnqXUiBl39JeQiLmHpRw",
                        kind="aws_ec2_network_acl",
                        name="acl-0854a97eb614d5ef2",
                        cloud="aws",
                        account="someengineering-development",
                        region="us-east-1",
                        zone=None,
                    ),
                ],
            ),
            FailedBenchmarkCheck(
                check_id="aws_s3_bucket_no_mfa_delete",
                title="Ensure S3 bucket MFA Delete is enabled.",
                severity="medium",
                failed_resources=1,
                examples=[
                    VulnerableResource(
                        id="sHJWmuw5bl-1WXRAS5aaog",
                        kind="aws_s3_bucket",
                        name="elasticbeanstalk-us-east-1-625596817853",
                        cloud="aws",
                        account="someengineering-development",
                        region="global",
                        zone=None,
                    )
                ],
            ),
            FailedBenchmarkCheck(
                check_id="aws_s3_account_level_public_access_blocks",
                title="Ensure S3 Account Level Public Access Block is Enabled",
                severity="high",
                failed_resources=1,
                examples=[
                    VulnerableResource(
                        id="sHJWmuw5bl-1WXRAS5aaog",
                        kind="aws_s3_bucket",
                        name="elasticbeanstalk-us-east-1-625596817853",
                        cloud="aws",
                        account="someengineering-development",
                        region="global",
                        zone=None,
                    )
                ],
            ),
        ],
        link="http://localhost:8000/inventory?q=%2Fsecurity.has_issues%3D%3Dtrue+and+%2Fsecurity.issues%5B%5D.%7Bbenchmarks%5B%5D%3D%3Daws_cis_2_0+and+run_id+in+%5Bmy_manual_sync%5D+and+severity+in+%5Bhigh%2Ccritical%5D%7D&before=2024-01-29T13%3A47%3A27Z&after=2023-01-29T13%3A47%3A27Z&change=node_vulnerable&limit=50",
    )
    a = sender.vulnerable_resources_detected(real)
    print(json.dumps(a, indent=2))
