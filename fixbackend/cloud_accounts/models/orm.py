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

import uuid
from datetime import datetime
from typing import Optional

from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.base_model import Base
from fixbackend.cloud_accounts import models
from fixbackend.ids import (
    AwsRoleName,
    AzureSubscriptionCredentialsId,
    CloudAccountAlias,
    CloudAccountId,
    CloudAccountName,
    CloudName,
    CloudNames,
    ExternalId,
    FixCloudAccountId,
    GcpServiceAccountKeyId,
    TaskId,
    UserCloudAccountName,
    WorkspaceId,
)
from fixbackend.sqlalechemy_extensions import UTCDateTime


class CloudAccount(Base):
    __tablename__ = "cloud_account"

    id: Mapped[FixCloudAccountId] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[WorkspaceId] = mapped_column(GUID, ForeignKey("organization.id"), nullable=False, index=True)
    cloud: Mapped[CloudName] = mapped_column(String(length=64), nullable=False)
    account_id: Mapped[CloudAccountId] = mapped_column(String(length=64), nullable=False)
    aws_external_id: Mapped[Optional[ExternalId]] = mapped_column(GUID, nullable=True)
    aws_role_name: Mapped[Optional[AwsRoleName]] = mapped_column(String(length=2048), nullable=True)
    gcp_service_account_key_id: Mapped[Optional[GcpServiceAccountKeyId]] = mapped_column(GUID, nullable=True)
    azure_credential_id: Mapped[Optional[AzureSubscriptionCredentialsId]] = mapped_column(GUID, nullable=True)
    privileged: Mapped[bool] = mapped_column(Boolean, nullable=False)
    user_account_name: Mapped[Optional[UserCloudAccountName]] = mapped_column(String(length=256), nullable=True)
    api_account_name: Mapped[Optional[CloudAccountName]] = mapped_column(String(length=256), nullable=True)
    api_account_alias: Mapped[Optional[CloudAccountAlias]] = mapped_column(String(length=256), nullable=True)
    is_configured: Mapped[bool] = mapped_column(Boolean, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    state: Mapped[Optional[str]] = mapped_column(String(length=64), nullable=True, index=True)
    error: Mapped[Optional[str]] = mapped_column(String(length=64), nullable=True)
    last_scan_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_scan_started_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    last_scan_resources_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_scan_resources_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    state_updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    cf_stack_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    version_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scan: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    failed_scan_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_task_id: Mapped[Optional[TaskId]] = mapped_column(String(length=64), nullable=True)
    last_degraded_scan_started_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "account_id"),)
    __mapper_args__ = {"version_id_col": version_id}  # for optimistic locking

    def to_model(self, next_scan: Optional[datetime]) -> models.CloudAccount:
        def access() -> models.CloudAccess:
            match self.cloud:
                case CloudNames.AWS:
                    if self.aws_role_name is None or self.aws_external_id is None:
                        raise ValueError("AWS role name or external_id is not set")
                    return models.AwsCloudAccess(
                        external_id=self.aws_external_id,
                        role_name=self.aws_role_name,
                    )
                case CloudNames.GCP:
                    if self.gcp_service_account_key_id is None:
                        raise ValueError("GCP service account key id is not set")
                    return models.GcpCloudAccess(
                        service_account_key_id=self.gcp_service_account_key_id,
                    )
                case CloudNames.Azure:
                    if self.azure_credential_id is None:
                        raise ValueError("Azure credential id is not set")
                    return models.AzureCloudAccess(
                        subscription_credentials_id=self.azure_credential_id,
                    )
                case _:
                    raise ValueError(f"Unknown cloud {self.cloud}")

        def state() -> models.CloudAccountState:
            match self.state:
                case None:  # backwards compatibility when we didn't have a state
                    if self.is_configured:
                        return models.CloudAccountStates.Configured(
                            access=access(), enabled=self.enabled, scan=self.scan
                        )
                    return models.CloudAccountStates.Discovered(access=access(), enabled=self.enabled)

                case models.CloudAccountStates.Detected.state_name:
                    return models.CloudAccountStates.Detected()
                case models.CloudAccountStates.Discovered.state_name:
                    return models.CloudAccountStates.Discovered(access=access(), enabled=self.enabled)
                case models.CloudAccountStates.Configured.state_name:
                    return models.CloudAccountStates.Configured(access=access(), enabled=self.enabled, scan=self.scan)
                case models.CloudAccountStates.Degraded.state_name:
                    if self.error is None:
                        raise ValueError("Degraded account must have an error")
                    return models.CloudAccountStates.Degraded(
                        access=access(), enabled=self.enabled, scan=self.scan, error=self.error
                    )
                case models.CloudAccountStates.Deleted.state_name:
                    return models.CloudAccountStates.Deleted()
                case _:
                    raise ValueError(f"Unknown state {self.state}")

        return models.CloudAccount(
            id=self.id,
            account_id=self.account_id,
            workspace_id=self.tenant_id,
            cloud=self.cloud,
            state=state(),
            account_name=self.api_account_name,
            account_alias=self.api_account_alias,
            user_account_name=self.user_account_name,
            privileged=self.privileged,
            next_scan=next_scan,
            last_scan_duration_seconds=self.last_scan_duration_seconds,
            last_scan_started_at=self.last_scan_started_at,
            last_scan_resources_scanned=self.last_scan_resources_scanned,
            last_scan_resources_errors=self.last_scan_resources_errors,
            created_at=self.created_at,
            updated_at=self.updated_at,
            state_updated_at=self.state_updated_at,
            cf_stack_version=self.cf_stack_version,
            failed_scan_count=self.failed_scan_count,
            last_task_id=self.last_task_id,
            last_degraded_scan_started_at=self.last_degraded_scan_started_at,
        )
