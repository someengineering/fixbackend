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
from sqlalchemy import ForeignKey, String, UniqueConstraint, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.base_model import Base
from fixbackend.cloud_accounts import models
from fixbackend.ids import WorkspaceId, FixCloudAccountId, ExternalId, CloudAccountId, AwsRoleName


class CloudAccount(Base):
    __tablename__ = "cloud_account"

    id: Mapped[FixCloudAccountId] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[WorkspaceId] = mapped_column(GUID, ForeignKey("organization.id"), nullable=False, index=True)
    cloud: Mapped[str] = mapped_column(String(length=12), nullable=False)
    account_id: Mapped[CloudAccountId] = mapped_column(String(length=12), nullable=False)
    aws_external_id: Mapped[Optional[ExternalId]] = mapped_column(GUID, nullable=True)
    aws_role_name: Mapped[Optional[AwsRoleName]] = mapped_column(String(length=64), nullable=True)
    privileged: Mapped[bool] = mapped_column(Boolean, nullable=False)
    user_account_name: Mapped[Optional[str]] = mapped_column(String(length=64), nullable=True)
    api_account_name: Mapped[Optional[str]] = mapped_column(String(length=64), nullable=True)
    api_account_alias: Mapped[Optional[str]] = mapped_column(String(length=64), nullable=True)
    is_configured: Mapped[bool] = mapped_column(Boolean, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    state: Mapped[Optional[str]] = mapped_column(String(length=64), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(String(length=64), nullable=True)
    __table_args__ = (UniqueConstraint("tenant_id", "account_id"),)

    def to_model(self) -> models.CloudAccount:
        def access() -> models.CloudAccess:
            match self.cloud:
                case "aws":
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
        )
