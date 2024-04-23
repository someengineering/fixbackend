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

from datetime import datetime
from typing import Annotated, Optional, Tuple, AsyncIterator, cast
from fastapi import Depends

from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import String, Boolean, select, Index, update, delete, Integer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.base_model import Base, CreatedUpdatedMixin
from fixbackend.billing.models import BillingEntry
from fixbackend.dependencies import FixDependency, ServiceNames
from fixbackend.ids import (
    ProductTier,
    WorkspaceId,
    UserId,
    SubscriptionId,
    BillingId,
    StripeCustomerId,
    StripeSubscriptionId,
)
from fixbackend.sqlalechemy_extensions import UTCDateTime
from fixbackend.subscription.models import (
    AwsMarketplaceSubscription,
    StripeSubscription,
    SubscriptionMethod,
    SubscriptionMethodType,
)
from fixbackend.types import AsyncSessionMaker
from fixbackend.utils import uid


class SubscriptionEntity(CreatedUpdatedMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (Index("idx_aws_customer_user", "aws_customer_identifier", "user_id"),)

    id: Mapped[SubscriptionId] = mapped_column(GUID, primary_key=True)
    user_id: Mapped[Optional[UserId]] = mapped_column(GUID, nullable=True, index=True)
    aws_customer_identifier: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    aws_customer_account_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default="")
    aws_product_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    stripe_customer_identifier: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default=None)
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default=None)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_charge_timestamp: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True, default=None)
    next_charge_timestamp: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True, default=None)

    def to_model(self) -> SubscriptionMethod:
        if self.stripe_subscription_id and self.stripe_customer_identifier:
            return StripeSubscription(
                id=self.id,
                customer_identifier=StripeCustomerId(self.stripe_customer_identifier),
                stripe_subscription_id=StripeSubscriptionId(self.stripe_subscription_id),
                active=self.active,
                last_charge_timestamp=self.last_charge_timestamp,
                next_charge_timestamp=self.next_charge_timestamp,
            )
        elif self.aws_customer_identifier and self.aws_customer_account_id and self.aws_product_code:
            return AwsMarketplaceSubscription(
                id=self.id,
                user_id=self.user_id,
                customer_identifier=self.aws_customer_identifier,
                customer_aws_account_id=self.aws_customer_account_id,
                product_code=self.aws_product_code,
                active=self.active,
                last_charge_timestamp=self.last_charge_timestamp,
                next_charge_timestamp=self.next_charge_timestamp,
            )
        else:
            raise ValueError("Subscription is neither AWS Marketplace nor Stripe")

    @staticmethod
    def from_model(subscription: SubscriptionMethod) -> SubscriptionEntity:
        if isinstance(subscription, AwsMarketplaceSubscription):
            return SubscriptionEntity(
                id=subscription.id,
                user_id=subscription.user_id,
                aws_customer_identifier=subscription.customer_identifier,
                aws_customer_account_id=subscription.customer_aws_account_id,
                aws_product_code=subscription.product_code,
                active=subscription.active,
                last_charge_timestamp=subscription.last_charge_timestamp,
                next_charge_timestamp=subscription.next_charge_timestamp,
            )
        elif isinstance(subscription, StripeSubscription):
            return SubscriptionEntity(
                id=subscription.id,
                user_id=None,
                stripe_customer_identifier=subscription.customer_identifier,
                stripe_subscription_id=subscription.stripe_subscription_id,
                active=subscription.active,
                last_charge_timestamp=subscription.last_charge_timestamp,
                next_charge_timestamp=subscription.next_charge_timestamp,
            )


class BillingEntity(CreatedUpdatedMixin, Base):
    __tablename__ = "billing"
    id: Mapped[BillingId] = mapped_column(GUID, primary_key=True)
    workspace_id: Mapped[WorkspaceId] = mapped_column(GUID, nullable=False, index=True)
    subscription_id: Mapped[SubscriptionId] = mapped_column(GUID, nullable=False, index=True)
    tier: Mapped[str] = mapped_column(String(64), nullable=False)
    nr_of_accounts_charged: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=None)
    period_end: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=None)
    reported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def to_model(self) -> BillingEntry:
        return BillingEntry(
            id=self.id,
            workspace_id=self.workspace_id,
            subscription_id=self.subscription_id,
            tier=ProductTier.from_str(self.tier),
            nr_of_accounts_charged=self.nr_of_accounts_charged,
            period_start=self.period_start,
            period_end=self.period_end,
            reported=self.reported,
        )

    @staticmethod
    def from_model(entry: BillingEntry) -> BillingEntity:
        return BillingEntity(
            id=entry.id,
            workspace_id=entry.workspace_id,
            subscription_id=entry.subscription_id,
            tier=entry.tier,
            nr_of_accounts_charged=entry.nr_of_accounts_charged,
            period_start=entry.period_start,
            period_end=entry.period_end,
            reported=entry.reported,
        )


class SubscriptionRepository:
    def __init__(self, session_maker: AsyncSessionMaker) -> None:
        self.session_maker = session_maker

    async def aws_marketplace_subscription(
        self, user_id: UserId, customer_identifier: str
    ) -> Optional[AwsMarketplaceSubscription]:
        async with self.session_maker() as session:
            stmt = (
                select(SubscriptionEntity)
                .where(SubscriptionEntity.aws_customer_identifier == customer_identifier)
                .where(SubscriptionEntity.user_id == user_id)
            )
            if result := (await session.execute(stmt)).scalar_one_or_none():
                return cast(AwsMarketplaceSubscription, result.to_model())
            else:
                return None

    async def mark_aws_marketplace_subscriptions(self, customer_identifier: str, active: bool) -> int:
        async with self.session_maker() as session:
            result = await session.execute(
                update(SubscriptionEntity)
                .where(SubscriptionEntity.aws_customer_identifier == customer_identifier)
                .values(active=active)
            )
            return result.rowcount  # noqa

    async def get_subscription(self, subscription_id: SubscriptionId) -> Optional[SubscriptionMethod]:
        async with self.session_maker() as session:
            stmt = select(SubscriptionEntity).where(SubscriptionEntity.id == subscription_id)
            if result := (await session.execute(stmt)).scalar_one_or_none():
                return result.to_model()
            else:
                return None

    async def subscriptions(
        self,
        *,
        user_id: Optional[UserId] = None,
        aws_customer_identifier: Optional[str] = None,
        stripe_customer_identifier: Optional[str] = None,
        stripe_subscription_identifier: Optional[StripeSubscriptionId] = None,
        active: Optional[bool] = None,
        next_charge_timestamp_before: Optional[datetime] = None,
        next_charge_timestamp_after: Optional[datetime] = None,
        session: Optional[AsyncSession] = None,
        is_aws_marketplace_subscription: Optional[bool] = None,
        is_stripe_subscription: Optional[bool] = None,
    ) -> AsyncIterator[SubscriptionMethod]:
        query = select(SubscriptionEntity)
        if user_id:
            query = query.where(SubscriptionEntity.user_id == user_id)
        if aws_customer_identifier:
            query = query.where(SubscriptionEntity.aws_customer_identifier == aws_customer_identifier)
        if active is not None:
            query = query.where(SubscriptionEntity.active == active)
        if next_charge_timestamp_before:
            query = query.where(SubscriptionEntity.next_charge_timestamp <= next_charge_timestamp_before)
        if next_charge_timestamp_after:
            query = query.where(SubscriptionEntity.next_charge_timestamp > next_charge_timestamp_after)
        if stripe_customer_identifier:
            query = query.where(SubscriptionEntity.stripe_customer_identifier == stripe_customer_identifier)
        if stripe_subscription_identifier:
            query = query.where(SubscriptionEntity.stripe_subscription_id == stripe_subscription_identifier)
        if (is_aws := is_aws_marketplace_subscription) is not None:
            aws_customer = SubscriptionEntity.aws_customer_identifier
            query = query.where(aws_customer.isnot(None) if is_aws else aws_customer.is_(None))
        if (is_stripe := is_stripe_subscription) is not None:
            stripe_sub = SubscriptionEntity.stripe_subscription_id
            query = query.where(stripe_sub.isnot(None) if is_stripe else stripe_sub.is_(None))

        if session:
            async for (subscription,) in await session.stream(query):
                yield subscription.to_model()
        else:
            async with self.session_maker() as session:
                async for (subscription,) in await session.stream(query):
                    yield subscription.to_model()

    async def unreported_aws_billing_entries(self) -> AsyncIterator[Tuple[BillingEntry, AwsMarketplaceSubscription]]:
        async with self.session_maker() as session:
            query = (
                select(BillingEntity, SubscriptionEntity)
                .join(SubscriptionEntity, BillingEntity.subscription_id == SubscriptionEntity.id)
                .where(BillingEntity.reported == False)  # noqa
                .where(SubscriptionEntity.aws_customer_identifier != None)  # noqa
            )
            async for billing_entity, subscription_entity in await session.stream(query):
                yield billing_entity.to_model(), cast(AwsMarketplaceSubscription, subscription_entity.to_model())

    async def unreported_stripe_billing_entries(self) -> AsyncIterator[Tuple[BillingEntry, StripeSubscription]]:
        async with self.session_maker() as session:
            query = (
                select(BillingEntity, SubscriptionEntity)
                .join(SubscriptionEntity, BillingEntity.subscription_id == SubscriptionEntity.id)
                .where(BillingEntity.reported == False)  # noqa
                .where(SubscriptionEntity.stripe_subscription_id != None)  # noqa
            )
            async for billing_entity, subscription_entity in await session.stream(query):
                yield billing_entity.to_model(), cast(StripeSubscription, subscription_entity.to_model())

    async def add_billing_entry(
        self,
        sid: SubscriptionId,
        workspace_id: WorkspaceId,
        tier: ProductTier,
        nr_of_accounts_charged: int,
        last_charge_timestamp: datetime,
        now: datetime,
        next_charge_timestamp: datetime,
    ) -> BillingEntry:
        async with self.session_maker() as session:
            # add billing entry
            billing_entity = BillingEntity(
                id=uid(),
                workspace_id=workspace_id,
                subscription_id=sid,
                tier=tier.value,
                nr_of_accounts_charged=nr_of_accounts_charged,
                period_start=last_charge_timestamp,
                period_end=now,
                reported=False,
            )
            result = billing_entity.to_model()
            session.add(billing_entity)
            # update the billing timestamps
            await session.execute(
                update(SubscriptionEntity)
                .where(SubscriptionEntity.id == sid)
                .values(
                    last_charge_timestamp=now,
                    next_charge_timestamp=next_charge_timestamp,
                )
            )
            await session.commit()
            return result

    async def update_charge_timestamp(self, sid: SubscriptionId, now: datetime, next_charge_timestamp: datetime) -> int:
        async with self.session_maker() as session:
            result = await session.execute(
                update(SubscriptionEntity)
                .where(SubscriptionEntity.id == sid)
                .values(
                    last_charge_timestamp=now,
                    next_charge_timestamp=next_charge_timestamp,
                )
            )
            await session.commit()
            return result.rowcount  # noqa

    async def delete_subscriptions(self, sid: SubscriptionId) -> int:
        async with self.session_maker() as session:
            result = await session.execute(delete(SubscriptionEntity).where(SubscriptionEntity.id == sid))
            await session.commit()
            return result.rowcount  # noqa

    async def delete_aws_marketplace_subscriptions(self, customer_identifier: str) -> int:
        async with self.session_maker() as session:
            result = await session.execute(
                delete(SubscriptionEntity).where(SubscriptionEntity.aws_customer_identifier == customer_identifier)
            )
            await session.commit()
            return result.rowcount  # noqa

    async def create(self, subscription: SubscriptionMethodType) -> SubscriptionMethodType:
        async with self.session_maker() as session:
            session.add(SubscriptionEntity.from_model(subscription))
            await session.commit()
            return subscription

    async def mark_billing_entry_reported(self, bid: BillingId) -> None:
        async with self.session_maker() as session:
            await session.execute(update(BillingEntity).where(BillingEntity.id == bid).values(reported=True))
            await session.commit()

    async def user_has_subscription(self, user_id: UserId, subscription_id: SubscriptionId) -> bool:
        async with self.session_maker() as session:
            stmt = (
                select(SubscriptionEntity)
                .where(SubscriptionEntity.id == subscription_id)
                .where(SubscriptionEntity.user_id == user_id)
            )
            return (await session.execute(stmt)).scalar_one_or_none() is not None

    async def list_billing_for_workspace(
        self, workspace_id: WorkspaceId
    ) -> AsyncIterator[Tuple[BillingEntry, SubscriptionMethod]]:
        async with self.session_maker() as session:
            query = (
                select(BillingEntity, SubscriptionEntity)
                .join(SubscriptionEntity, BillingEntity.subscription_id == SubscriptionEntity.id)
                .where(BillingEntity.workspace_id == workspace_id)  # noqa
            )
            async for billing_entity, subscription_entity in await session.stream(query):
                yield billing_entity.to_model(), subscription_entity.to_model()


class StripeCustomerEntity(CreatedUpdatedMixin, Base):
    __tablename__ = "stripe_customers"
    workspace_id: Mapped[WorkspaceId] = mapped_column(GUID, nullable=False, primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)


class StripeCustomerRepository:
    def __init__(self, session_maker: AsyncSessionMaker) -> None:
        self.session_maker = session_maker

    async def get(self, workspace_id: WorkspaceId) -> Optional[StripeCustomerId]:
        async with self.session_maker() as session:
            stmt = select(StripeCustomerEntity).where(StripeCustomerEntity.workspace_id == workspace_id)
            if result := (await session.execute(stmt)).scalar_one_or_none():
                return StripeCustomerId(result.customer_id)
            else:
                return None

    async def workspace_of_customer(self, customer_id: StripeCustomerId) -> Optional[WorkspaceId]:
        async with self.session_maker() as session:
            stmt = select(StripeCustomerEntity.workspace_id).where(StripeCustomerEntity.customer_id == customer_id)
            if result := (await session.execute(stmt)).scalar_one_or_none():
                return result
            else:
                return None

    async def create(self, workspace_id: WorkspaceId, customer_id: StripeCustomerId) -> None:
        async with self.session_maker() as session:
            entity = StripeCustomerEntity(workspace_id=workspace_id, customer_id=customer_id)
            session.add(entity)
            await session.commit()


def get_subscription_repository(fix: FixDependency) -> SubscriptionRepository:
    return fix.service(ServiceNames.subscription_repo, SubscriptionRepository)


SubscriptionRepositoryDependency = Annotated[SubscriptionRepository, Depends(get_subscription_repository)]
