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
from fixbackend.ids import TenantId, CloudAccountId
from fixbackend.cloud_accounts import models as domain


class CloudAccount(Base):
    __tablename__ = "cloud_account"

    id: Mapped[CloudAccountId] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[TenantId] = mapped_column(GUID, ForeignKey("organization.id"), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(length=12), nullable=False)
    role_name: Mapped[str] = mapped_column(String(length=64), nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "account_id"),)

    def to_domain(self) -> domain.CloudAccount:
        return domain.CloudAccount(
            id=self.id,
            tenant_id=self.tenant_id,
            account_id=self.account_id,
            role_name=self.role_name,
        )
