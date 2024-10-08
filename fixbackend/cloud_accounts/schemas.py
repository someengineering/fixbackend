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

from fixbackend.cloud_accounts.models import (
    AzureSubscriptionCredentials,
    CloudAccount,
    CloudAccountStates,
    GcpServiceAccountKey,
)
from fixbackend.ids import (
    AwsRoleName,
    AzureSubscriptionCredentialsId,
    CloudAccountAlias,
    CloudAccountId,
    CloudAccountName,
    ExternalId,
    FixCloudAccountId,
    GcpServiceAccountKeyId,
    UserCloudAccountName,
    WorkspaceId,
)


class AwsCloudFormationLambdaCallbackParameters(BaseModel):
    workspace_id: WorkspaceId = Field(description="Your Fix-assigned Workspace ID")
    external_id: ExternalId = Field(description="Your Fix-assigned External ID")
    account_id: CloudAccountId = Field(description="AWS account ID", pattern=r"^\d{12}$")
    role_name: AwsRoleName = Field(description="AWS role name", max_length=2048)
    fix_stack_version: int = Field(description="The version of the Fix stack")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "workspace_id": "00000000-0000-0000-0000-000000000000",
                    "external_id": "00000000-0000-0000-0000-000000000000",
                    "account_id": "123456789012",
                    "role_name": "FooBarRole",
                    "fix_stack_version": 1708513196,
                }
            ]
        }
    }


class CloudAccountRead(BaseModel):
    id: FixCloudAccountId = Field(description="Fix internal cloud account ID, users should not typically see this")
    cloud: str = Field(description="Cloud provider")
    account_id: CloudAccountId = Field(description="Cloud account ID, as defined by the cloud provider")
    enabled: bool = Field(description="Whether the cloud account is enabled for collection")
    scan: bool = Field(description="Whether the cloud account should be scanned for resources")
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
    privileged: bool = Field(description="If privileged, the account can do some administrative tasks")
    last_scan_started_at: Optional[datetime] = Field(description="The time when the last scan started")
    last_scan_finished_at: Optional[datetime] = Field(description="The time when the last scan finished")
    cf_stack_version: Optional[int] = Field(description="The version of the corresponting CF stack")
    errors: Optional[int] = Field(description="Number of errors during the last scan")

    @staticmethod
    def from_model(model: CloudAccount) -> "CloudAccountRead":
        enabled = False
        is_configured = False
        scan = False
        match model.state:
            case CloudAccountStates.Configured():
                enabled = model.state.enabled
                scan = model.state.scan
                is_configured = True

            case CloudAccountStates.Degraded():
                enabled = model.state.enabled
                scan = model.state.scan

        last_scan_finished = None
        if model.last_scan_started_at:
            last_scan_finished = model.last_scan_started_at + timedelta(seconds=model.last_scan_duration_seconds)

        return CloudAccountRead(
            id=model.id,
            cloud=model.cloud,
            account_id=model.account_id,
            user_account_name=model.user_account_name,
            enabled=enabled,
            scan=scan,
            is_configured=is_configured,
            resources=model.last_scan_resources_scanned,
            next_scan=model.next_scan,
            api_account_alias=model.account_alias,
            api_account_name=model.account_name,
            state=model.state.state_name,
            privileged=model.privileged,
            last_scan_started_at=model.last_scan_started_at,
            last_scan_finished_at=last_scan_finished,
            cf_stack_version=model.cf_stack_version,
            errors=model.last_scan_resources_errors,
        )


class CloudAccountList(BaseModel):
    recent: List[CloudAccountRead] = Field(description="List of recently used cloud accounts")
    added: List[CloudAccountRead] = Field(description="List of added cloud accounts")
    discovered: List[CloudAccountRead] = Field(description="List of discovered cloud accounts")


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


class GcpServiceAccountKeyRead(BaseModel):
    id: GcpServiceAccountKeyId
    workspace_id: WorkspaceId
    can_access_sa: Optional[bool]
    created_at: datetime
    error: Optional[str]

    @staticmethod
    def from_model(model: GcpServiceAccountKey) -> "GcpServiceAccountKeyRead":
        return GcpServiceAccountKeyRead(
            id=model.id,
            workspace_id=model.tenant_id,
            can_access_sa=model.can_access_sa,
            created_at=model.created_at,
            error=model.error,
        )


class AzureSubscriptionCredentialsUpdate(BaseModel):
    azure_tenant_id: str
    client_id: str
    client_secret: str


class AzureSubscriptionCredentialsRead(BaseModel):
    id: AzureSubscriptionCredentialsId
    workspace_id: WorkspaceId
    can_access_azure_account: Optional[bool]
    created_at: datetime
    azure_tenant_id: str
    client_id: str

    @staticmethod
    def from_model(model: AzureSubscriptionCredentials) -> "AzureSubscriptionCredentialsRead":
        return AzureSubscriptionCredentialsRead(
            id=model.id,
            workspace_id=model.tenant_id,
            can_access_azure_account=model.can_access_azure_account,
            created_at=model.created_at,
            azure_tenant_id=model.azure_tenant_id,
            client_id=model.client_id,
        )
