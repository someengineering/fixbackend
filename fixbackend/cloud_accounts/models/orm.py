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

from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.base_model import Base
from fixbackend.cloud_accounts import models
from fixbackend.ids import WorkspaceId, FixCloudAccountId, ExternalId, CloudAccountId


class CloudAccount(Base):
    __tablename__ = "cloud_account"

    id: Mapped[FixCloudAccountId] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[WorkspaceId] = mapped_column(GUID, ForeignKey("organization.id"), nullable=False, index=True)
    cloud: Mapped[str] = mapped_column(String(length=12), nullable=False)
    account_id: Mapped[CloudAccountId] = mapped_column(String(length=12), nullable=False)
    aws_external_id: Mapped[ExternalId] = mapped_column(GUID, nullable=False)
    aws_role_name: Mapped[str] = mapped_column(String(length=64), nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "account_id"),)

    def to_model(self) -> models.CloudAccount:
        def access() -> models.CloudAccess:
            match self.cloud:
                case "aws":
                    return models.AwsCloudAccess(
                        account_id=self.account_id, external_id=self.aws_external_id, role_name=self.aws_role_name
                    )
                case _:
                    raise ValueError(f"Unknown cloud {self.cloud}")

        return models.CloudAccount(id=self.id, workspace_id=self.tenant_id, access=access())
