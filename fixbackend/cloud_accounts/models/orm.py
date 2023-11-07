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
    aws_external_id: Mapped[ExternalId] = mapped_column(GUID, nullable=False)
    aws_role_name: Mapped[Optional[AwsRoleName]] = mapped_column(String(length=64), nullable=True)
    aws_can_discover_names: Mapped[bool] = mapped_column(Boolean, nullable=False)
    user_account_name: Mapped[Optional[str]] = mapped_column(String(length=64), nullable=True)
    api_account_name: Mapped[Optional[str]] = mapped_column(String(length=64), nullable=True)
    api_account_alias: Mapped[Optional[str]] = mapped_column(String(length=64), nullable=True)
    is_configured: Mapped[bool] = mapped_column(Boolean, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "account_id"),)

    def to_model(self) -> models.CloudAccount:
        def access() -> models.CloudAccess:
            match self.cloud:
                case "aws":
                    return models.AwsCloudAccess(
                        aws_account_id=self.account_id,
                        external_id=self.aws_external_id,
                        role_name=self.aws_role_name,
                        can_discover_names=self.aws_can_discover_names,
                    )
                case _:
                    raise ValueError(f"Unknown cloud {self.cloud}")

        return models.CloudAccount(
            id=self.id,
            workspace_id=self.tenant_id,
            access=access(),
            api_account_name=self.api_account_name,
            is_configured=self.is_configured,
            enabled=self.enabled,
            api_account_alias=self.api_account_alias,
            user_account_name=self.user_account_name,
        )
