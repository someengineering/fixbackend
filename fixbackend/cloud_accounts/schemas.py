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

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from fixbackend.ids import WorkspaceId, ExternalId, CloudAccountId, FixCloudAccountId
from fixbackend.cloud_accounts.models import CloudAccount, LastScanAccountInfo


class AwsCloudFormationLambdaCallbackParameters(BaseModel):
    workspace_id: WorkspaceId = Field(description="Your FIX-assigned Workspace ID")
    external_id: ExternalId = Field(description="Your FIX-assigned External ID")
    account_id: CloudAccountId = Field(description="AWS account ID", pattern=r"^\d{12}$")
    role_name: str = Field(description="AWS role name", max_length=64)

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
    id: FixCloudAccountId = Field(description="Fix cloud account ID")
    cloud: str = Field(description="Cloud provider")
    account_id: CloudAccountId = Field(description="Cloud account ID, as defined by the cloud provider")
    name: Optional[str] = Field(description="Name of the cloud account", max_length=64)
    enabled: bool = Field(description="Whether the cloud account is enabled for collection")
    is_configured: bool = Field(description="Is account correctly configured")
    resources: Optional[int] = Field(description="Number of resources in the account")
    next_scan: Optional[datetime] = Field(description="Next scheduled scan")

    @staticmethod
    def from_model(
        model: CloudAccount, last_scan_info: Optional[LastScanAccountInfo] = None, next_scan: Optional[datetime] = None
    ) -> "CloudAccountRead":
        return CloudAccountRead(
            id=model.id,
            cloud=model.access.cloud,
            account_id=model.access.account_id(),
            name=model.name,
            enabled=model.enabled,
            is_configured=model.is_configured,
            resources=last_scan_info.resources_scanned if last_scan_info else None,
            next_scan=next_scan,
        )


class AwsCloudAccountUpdate(BaseModel):
    name: str = Field(description="Name of the cloud account", max_length=64)


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
