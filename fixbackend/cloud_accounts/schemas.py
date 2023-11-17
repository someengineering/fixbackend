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

from datetime import datetime, timedelta
from typing import List, Optional

from pydantic import BaseModel, Field

from fixbackend.cloud_accounts.models import CloudAccount, CloudAccountStates
from fixbackend.ids import (
    AwsRoleName,
    CloudAccountAlias,
    CloudAccountId,
    CloudAccountName,
    ExternalId,
    FixCloudAccountId,
    UserCloudAccountName,
    WorkspaceId,
)


class AwsCloudFormationLambdaCallbackParameters(BaseModel):
    workspace_id: WorkspaceId = Field(description="Your FIX-assigned Workspace ID")
    external_id: ExternalId = Field(description="Your FIX-assigned External ID")
    account_id: CloudAccountId = Field(description="AWS account ID", pattern=r"^\d{12}$")
    role_name: AwsRoleName = Field(description="AWS role name", max_length=64)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "workspace_id": "00000000-0000-0000-0000-000000000000",
                    "external_id": "00000000-0000-0000-0000-000000000000",
                    "account_id": "123456789012",
                    "role_name": "FooBarRole",
                }
            ]
        }
    }


class CloudAccountRead(BaseModel):
    id: FixCloudAccountId = Field(description="Fix internal cloud account ID, users should not typically see this")
    cloud: str = Field(description="Cloud provider")
    account_id: CloudAccountId = Field(description="Cloud account ID, as defined by the cloud provider")
    enabled: bool = Field(description="Whether the cloud account is enabled for collection")
    is_configured: bool = Field(description="Is account correctly configured")
    resources: Optional[int] = Field(description="Number of resources in the account")
    next_scan: Optional[datetime] = Field(description="Next scheduled scan")
    user_account_name: Optional[UserCloudAccountName] = Field(
        description="Name of the cloud account, as set by the user", max_length=64
    )
    api_account_alias: Optional[CloudAccountAlias] = Field(
        description="Alias of the cloud account, provided by the cloud", max_length=64
    )
    api_account_name: Optional[CloudAccountName] = Field(
        description="Name of the cloud account, as provided by the cloud", max_length=64
    )
    state: str = Field(description="State of the cloud account")
    priviledged: bool = Field(description="If priviledged, the account can do some administative tasks")
    last_collected: Optional[datetime] = Field(description="The time when the account was last collected")

    @staticmethod
    def from_model(model: CloudAccount) -> "CloudAccountRead":
        enabled = False
        is_configured = False
        match model.state:
            case CloudAccountStates.Configured():
                enabled = model.state.enabled
                is_configured = True

        last_collected = None
        if model.last_scan_started_at:
            last_collected = model.last_scan_started_at + timedelta(seconds=model.last_scan_duration_seconds)

        return CloudAccountRead(
            id=model.id,
            cloud=model.cloud,
            account_id=model.account_id,
            user_account_name=model.user_account_name,
            enabled=enabled,
            is_configured=is_configured,
            resources=model.last_scan_resources_scanned,
            next_scan=model.next_scan,
            api_account_alias=model.account_alias,
            api_account_name=model.account_name,
            state=model.state.state_name,
            priviledged=model.privileged,
            last_collected=last_collected,
        )


class AwsCloudAccountUpdate(BaseModel):
    name: Optional[UserCloudAccountName] = Field(None, description="Name of the cloud account", max_length=64)


class ScannedAccount(BaseModel):
    account_id: CloudAccountId = Field(description="Cloud account ID")
    resource_scanned: int = Field(description="Number of resources scanned")
    duration: int = Field(description="Duration of the scan in seconds")
    started_at: datetime = Field(description="Time when the scan started")


class LastScanInfo(BaseModel):
    workspace_id: WorkspaceId = Field(description="Id of the workspace where the scan was performed")
    accounts: List[ScannedAccount] = Field(description="List of accounts scanned")
    next_scan: Optional[datetime] = Field(description="Next scheduled scan")

    @staticmethod
    def empty(workspace_id: WorkspaceId) -> "LastScanInfo":
        return LastScanInfo(workspace_id=workspace_id, accounts=[], next_scan=None)
