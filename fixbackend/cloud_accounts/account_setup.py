#  Copyright (c) 2023. Some Engineering
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

import boto3

import logging
from fixcloudutils.asyncio.async_extensions import run_async
from fixbackend.ids import ExternalId


log = logging.getLogger(__name__)


class AwsAccountSetupHelper:
    def __init__(self, session: boto3.Session) -> None:
        self.sts_client = session.client("sts")

    async def can_assume_role(self, account_id: str, role_name: str, external_id: ExternalId) -> bool:
        try:
            result = await run_async(
                self.sts_client.assume_role,
                RoleArn=f"arn:aws:iam::{account_id}:role/{role_name}",
                RoleSessionName="fix-account-preflight-check",
                ExternalId=str(external_id),
            )
            if not result.get("Credentials", {}).get("AccessKeyId"):
                return False
            return True
        except Exception as ex:
            log.warn(f"Failed to assume role: {ex}")
            return False
