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

from typing import Optional

from fastapi_users_db_sqlalchemy.generics import GUID
from fixbackend.sqlalechemy_extensions import UTCDateTime
from sqlalchemy import ForeignKey, String, UniqueConstraint, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from fixbackend.base_model import Base
from fixbackend.cloud_accounts import models
from fixbackend.ids import (
    WorkspaceId,
    FixCloudAccountId,
    ExternalId,
    CloudAccountId,
    AwsRoleName,
    CloudName,
    CloudNames,
    CloudAccountName,
    CloudAccountAlias,
    UserCloudAccountName,
)


class CloudAccount(Base):
    __tablename__ = "cloud_account"

    id: Mapped[FixCloudAccountId] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[WorkspaceId] = mapped_column(GUID, ForeignKey("organization.id"), nullable=False, index=True)
    cloud: Mapped[CloudName] = mapped_column(String(length=12), nullable=False)
    account_id: Mapped[CloudAccountId] = mapped_column(String(length=12), nullable=False)
    aws_external_id: Mapped[Optional[ExternalId]] = mapped_column(GUID, nullable=True)
    aws_role_name: Mapped[Optional[AwsRoleName]] = mapped_column(String(length=2048), nullable=True)
    privileged: Mapped[bool] = mapped_column(Boolean, nullable=False)
    user_account_name: Mapped[Optional[UserCloudAccountName]] = mapped_column(String(length=256), nullable=True)
    api_account_name: Mapped[Optional[CloudAccountName]] = mapped_column(String(length=256), nullable=True)
    api_account_alias: Mapped[Optional[CloudAccountAlias]] = mapped_column(String(length=256), nullable=True)
    is_configured: Mapped[bool] = mapped_column(Boolean, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    state: Mapped[Optional[str]] = mapped_column(String(length=64), nullable=True, index=True)
    error: Mapped[Optional[str]] = mapped_column(String(length=64), nullable=True)
    next_scan: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    last_scan_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_scan_started_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    last_scan_resources_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    state_updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    version_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("tenant_id", "account_id"),)
    __mapper_args__ = {"version_id_col": version_id}  # for optimistic locking

    def to_model(self) -> models.CloudAccount:
        def access() -> models.CloudAccess:
            match self.cloud:
                case CloudNames.AWS:
                    if self.aws_role_name is None or self.aws_external_id is None:
                        raise ValueError("AWS role name or external_id is not set")
                    return models.AwsCloudAccess(
                        external_id=self.aws_external_id,
                        role_name=self.aws_role_name,
                    )
                case _:
                    raise ValueError(f"Unknown cloud {self.cloud}")

        def state() -> models.CloudAccountState:
            match self.state:
                case None:  # backwards compatibility when we didn't have a state
                    if self.is_configured:
                        return models.CloudAccountStates.Configured(access=access(), enabled=self.enabled)
                    return models.CloudAccountStates.Discovered(access=access())

                case models.CloudAccountStates.Detected.state_name:
                    return models.CloudAccountStates.Detected()
                case models.CloudAccountStates.Discovered.state_name:
                    return models.CloudAccountStates.Discovered(access=access())
                case models.CloudAccountStates.Configured.state_name:
                    return models.CloudAccountStates.Configured(access=access(), enabled=self.enabled)
                case models.CloudAccountStates.Degraded.state_name:
                    if self.error is None:
                        raise ValueError("Degraded account must have an error")
                    return models.CloudAccountStates.Degraded(access=access(), error=self.error)
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
            next_scan=self.next_scan,
            last_scan_duration_seconds=self.last_scan_duration_seconds,
            last_scan_started_at=self.last_scan_started_at,
            last_scan_resources_scanned=self.last_scan_resources_scanned,
            created_at=self.created_at,
            updated_at=self.updated_at,
            state_updated_at=self.state_updated_at,
        )
