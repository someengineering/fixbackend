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

from abc import ABC
import logging
from typing import Optional, Dict
from fixcloudutils.asyncio.async_extensions import run_async
from fixbackend.ids import ExternalId, CloudAccountAlias, CloudAccountName
from attrs import frozen
from datetime import datetime
from fixbackend.ids import CloudAccountId, AwsRoleName

log = logging.getLogger(__name__)


class AssumeRoleResult(ABC):
    pass


class AssumeRoleResults:
    @frozen
    class Success(AssumeRoleResult):
        access_key_id: str
        secret_access_key: str
        session_token: str
        expiration: datetime

    @frozen
    class Failure(AssumeRoleResult):
        reason: str


class AwsAccountSetupHelper:
    def __init__(self, session: boto3.Session) -> None:
        self.sts_client = session.client("sts")
        self.organizations_client = session.client("organizations")

    async def can_assume_role(
        self, account_id: CloudAccountId, role_name: AwsRoleName, external_id: ExternalId
    ) -> AssumeRoleResult:
        try:
            result = await run_async(
                self.sts_client.assume_role,
                RoleArn=f"arn:aws:iam::{account_id}:role/{role_name}",
                RoleSessionName="fix-account-preflight-check",
                ExternalId=str(external_id),
            )
            if not result.get("Credentials", {}).get("AccessKeyId"):
                return AssumeRoleResults.Failure("Failed to assume role, no access key id in the response")

            return AssumeRoleResults.Success(
                access_key_id=result["Credentials"]["AccessKeyId"],
                secret_access_key=result["Credentials"]["SecretAccessKey"],
                session_token=result["Credentials"]["SessionToken"],
                expiration=result["Credentials"]["Expiration"],
            )

        except Exception as ex:
            return AssumeRoleResults.Failure(str(ex))

    async def list_accounts(
        self, assume_role_result: AssumeRoleResults.Success
    ) -> Dict[CloudAccountId, CloudAccountName]:
        session = boto3.Session(
            aws_access_key_id=assume_role_result.access_key_id,
            aws_secret_access_key=assume_role_result.secret_access_key,
            aws_session_token=assume_role_result.session_token,
        )
        orgnizations_client = session.client("organizations")
        accounts = []
        next_token = None
        try:
            while True:
                response = await run_async(
                    orgnizations_client.list_accounts,
                    NextToken=next_token,
                )
                next_token = response.get("NextToken")
                accounts.extend(response["Accounts"])
                if next_token is None:
                    break
        except Exception as ex:
            log.info("Failed to list accounts: %s", ex)
            return {}

        return {CloudAccountId(account["Id"]): CloudAccountName(account["Name"]) for account in accounts}

    async def list_account_aliases(self, assume_role_result: AssumeRoleResults.Success) -> Optional[CloudAccountAlias]:
        session = boto3.Session(
            aws_access_key_id=assume_role_result.access_key_id,
            aws_secret_access_key=assume_role_result.secret_access_key,
            aws_session_token=assume_role_result.session_token,
        )
        iam_client = session.client("iam")
        try:
            response = await run_async(iam_client.list_account_aliases)
            aliases = response.get("AccountAliases", [])
            return None if len(aliases) == 0 else CloudAccountAlias(aliases[0])
        except Exception:
            return None
