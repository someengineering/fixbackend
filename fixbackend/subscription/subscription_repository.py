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
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import String, Boolean, select, Index
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.base_model import Base, CreatedUpdatedMixin
from fixbackend.ids import WorkspaceId, UserId, PaymentMethodId
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.types import AsyncSessionMaker


class SubscriptionEntity(CreatedUpdatedMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (Index("idx_aws_customer_user", "aws_customer_identifier", "user_id"),)

    id: Mapped[UUID] = mapped_column(GUID, primary_key=True)
    user_id: Mapped[Optional[UserId]] = mapped_column(GUID, nullable=True, index=True)
    workspace_id: Mapped[Optional[WorkspaceId]] = mapped_column(GUID, nullable=True, index=True)
    aws_customer_identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    aws_customer_account_id: Mapped[str] = mapped_column(String(128), nullable=True, default="")
    aws_product_code: Mapped[str] = mapped_column(String(128), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def to_model(self) -> AwsMarketplaceSubscription:
        return AwsMarketplaceSubscription(
            id=PaymentMethodId(self.id),
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            customer_identifier=self.aws_customer_identifier,
            customer_aws_account_id=self.aws_customer_account_id,
            product_code=self.aws_product_code,
            active=self.active,
        )

    @staticmethod
    def from_model(subscription: AwsMarketplaceSubscription) -> SubscriptionEntity:
        return SubscriptionEntity(
            id=subscription.id,
            user_id=subscription.user_id,
            workspace_id=subscription.workspace_id,
            aws_customer_identifier=subscription.customer_identifier,
            aws_customer_account_id=subscription.customer_aws_account_id,
            aws_product_code=subscription.product_code,
            active=subscription.active,
        )


class SubscriptionRepository:
    def __init__(self, session_maker: AsyncSessionMaker) -> None:
        self.session_maker = session_maker

    async def aws_marketplace_subscription(
        self, user_id: UserId, customer_identifier: str
    ) -> Optional[AwsMarketplaceSubscription]:
        async with self.session_maker() as session:
            stmt = select(SubscriptionEntity).where(
                SubscriptionEntity.aws_customer_identifier == customer_identifier
                and SubscriptionEntity.user_id == user_id
            )
            if result := (await session.execute(stmt)).scalar_one_or_none():
                return result.to_model()
            else:
                return None

    async def create(self, subscription: AwsMarketplaceSubscription) -> AwsMarketplaceSubscription:
        async with self.session_maker() as session:
            session.add(SubscriptionEntity.from_model(subscription))
            await session.commit()
            return subscription
