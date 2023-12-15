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

from typing import Annotated, List, Optional

from fastapi import Depends
from fixbackend.db import AsyncSessionMakerDependency

from fixbackend.ids import UserId
from fixbackend.types import AsyncSessionMaker
from fixbackend.invoices.models import BillingAdderss

from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import select, String
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.base_model import Base
from fixbackend.errors import ResourceNotFound


class BillingAddressEntity(Base):
    __tablename__ = "billing_address"

    user_id: Mapped[UserId] = mapped_column(GUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    company: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    address_line_1: Mapped[str] = mapped_column(String(256), nullable=False)
    address_line_2: Mapped[str] = mapped_column(String(256), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(256), nullable=False)
    city: Mapped[str] = mapped_column(String(256), nullable=False)
    state: Mapped[str] = mapped_column(String(256), nullable=False)
    country: Mapped[str] = mapped_column(String(256), nullable=False)

    def to_model(self) -> BillingAdderss:
        return BillingAdderss(
            user_id=self.user_id,
            name=self.name,
            company=self.company,
            address_line_1=self.address_line_1,
            address_line_2=self.address_line_2,
            postal_code=self.postal_code,
            city=self.city,
            state=self.state,
            country=self.country,
        )


class BillingAddressRepository:
    def __init__(self, session_maker: AsyncSessionMaker) -> None:
        self.session_maker = session_maker

    async def get_billing_address(self, user_id: UserId) -> Optional[BillingAdderss]:
        async with self.session_maker() as session:
            result = await session.execute(select(BillingAddressEntity).where(BillingAddressEntity.user_id == user_id))
            entity = result.scalars().first()
            if not entity:
                return None
            return entity.to_model()

    async def list_billing_addresses(self, user_ids: List[UserId]) -> List[BillingAdderss]:
        async with self.session_maker() as session:
            result = await session.execute(
                select(BillingAddressEntity).where(BillingAddressEntity.user_id.in_(user_ids))
            )
            entities = result.scalars().all()
            models = [entity.to_model() for entity in entities]
            return models

    async def create_billing_address(self, user_id: UserId, billing_address: BillingAdderss) -> BillingAdderss:
        if info := await self.get_billing_address(user_id):
            return info

        async with self.session_maker() as session:
            entity = BillingAddressEntity(
                user_id=user_id,
                name=billing_address.name,
                company=billing_address.company,
                address_line_1=billing_address.address_line_1,
                address_line_2=billing_address.address_line_2,
                postal_code=billing_address.postal_code,
                city=billing_address.city,
                state=billing_address.state,
                country=billing_address.country,
            )
            session.add(entity)
            await session.commit()
            await session.refresh(entity)
            return entity.to_model()

    async def update_billing_address(self, user_id: UserId, billing_address: BillingAdderss) -> BillingAdderss:
        async with self.session_maker() as session:
            if entity := await session.get(BillingAddressEntity, user_id):
                entity.name = billing_address.name
                entity.company = billing_address.company
                entity.address_line_1 = billing_address.address_line_1
                entity.address_line_2 = billing_address.address_line_2
                entity.postal_code = billing_address.postal_code
                entity.city = billing_address.city
                entity.state = billing_address.state
                entity.country = billing_address.country

                await session.commit()
                await session.refresh(entity)
                return entity.to_model()
            else:
                raise ResourceNotFound(f"Billing address for user {user_id} not found")


def get_billing_address_repository(session_maker: AsyncSessionMakerDependency) -> BillingAddressRepository:
    return BillingAddressRepository(session_maker)


BillingAddressRepositoryDependency = Annotated[BillingAddressRepository, Depends(get_billing_address_repository)]
