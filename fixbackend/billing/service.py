#  Copyright (c) 2023-2024. Some Engineering
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


import logging
from datetime import datetime, timedelta
from typing import Annotated, List
from typing import Optional

from fastapi import Depends
from fixcloudutils.util import utc
from prometheus_client import Counter

from fixbackend.auth.models import User
from fixbackend.billing.models import (
    PaymentMethod,
    PaymentMethods,
    WorkspacePaymentMethods,
    BillingEntry,
)
from fixbackend.dependencies import FixDependency, ServiceNames
from fixbackend.domain_events.events import BillingEntryCreated
from fixbackend.domain_events.events import ProductTierChanged
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.errors import NotAllowed
from fixbackend.ids import ProductTier, BillingPeriod
from fixbackend.ids import UserId, WorkspaceId
from fixbackend.metering.metering_repository import MeteringRepository
from fixbackend.subscription.models import AwsMarketplaceSubscription, StripeSubscription, SubscriptionMethod
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.utils import start_of_next_period
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository

log = logging.getLogger(__name__)
AccountsCharged = Counter("billing_accounts_charged", "Accounts charged by security tier", ["product_tier"])


def compute_billing_period_factor(
    *,
    billing_time: datetime,
    last_charged: datetime,
    period_value: timedelta,
) -> float:
    delta = billing_time - last_charged
    # Default should be a single month. For shorter or longer periods, we use a fraction/factor of the month
    period_lower_bound = period_value - period_value * 0.1667  # - 5 days in case of 30 days
    period_upper_bound = period_value + period_value * 0.1667  # + 5 days in case of 30 days
    is_full_period = period_lower_bound < delta < period_upper_bound
    billing_factor = 1.0 if is_full_period else delta / period_value
    return billing_factor


class BillingEntryService:
    def __init__(
        self,
        subscription_repository: SubscriptionRepository,
        workspace_repository: WorkspaceRepository,
        metering_repository: MeteringRepository,
        domain_event_sender: DomainEventPublisher,
        billing_period: BillingPeriod,
    ) -> None:
        self.subscription_repository = subscription_repository
        self.workspace_repository = workspace_repository
        self.metering_repository = metering_repository
        self.domain_event_sender = domain_event_sender
        self.billing_period = billing_period

    async def list_billing_info(self, workspace_id: WorkspaceId) -> List[BillingEntry]:
        billing_entries = [
            billing async for billing, _ in self.subscription_repository.list_billing_for_workspace(workspace_id)
        ]
        return billing_entries

    async def get_payment_methods(self, workspace: Workspace, user_id: UserId) -> WorkspacePaymentMethods:
        """List all awailable payment methods available for the workspace"""
        current: PaymentMethod = PaymentMethods.NoPaymentMethod()

        payment_methods: List[PaymentMethod] = []
        if workspace.product_tier == ProductTier.Free or workspace.product_tier == ProductTier.Trial:
            payment_methods.append(PaymentMethods.NoPaymentMethod())

        async def get_current_subscription() -> Optional[SubscriptionMethod]:
            if workspace.subscription_id is None:
                return None

            if not (subscription := await self.subscription_repository.get_subscription(workspace.subscription_id)):
                return None

            if not subscription.active:
                return None

            return subscription

        if current_subscription := await get_current_subscription():
            match current_subscription:
                case AwsMarketplaceSubscription():
                    current = PaymentMethods.AwsSubscription(subscription_id=current_subscription.id)
                case StripeSubscription():
                    current = PaymentMethods.StripeSubscription(subscription_id=current_subscription.id)

        async for subscription in self.subscription_repository.subscriptions(user_id=user_id, active=True):
            match subscription:
                case AwsMarketplaceSubscription():
                    payment_methods.append(PaymentMethods.AwsSubscription(subscription_id=subscription.id))
                case StripeSubscription():
                    payment_methods.append(PaymentMethods.StripeSubscription(subscription_id=subscription.id))

        return WorkspacePaymentMethods(current=current, available=payment_methods)

    async def update_billing(
        self,
        user: User,
        workspace: Workspace,
        new_product_tier: Optional[ProductTier] = None,
        new_payment_method: Optional[PaymentMethod] = None,
    ) -> Workspace:
        current_tier = workspace.product_tier
        workspace_payment_methods = await self.get_payment_methods(workspace, user.id)

        def payment_method_available() -> bool:
            new_payment_method_provided = (
                new_payment_method is not None and new_payment_method is not PaymentMethods.NoPaymentMethod()
            )
            has_existing_payment_method = workspace_payment_methods.current is not PaymentMethods.NoPaymentMethod()
            return new_payment_method_provided or has_existing_payment_method

        # validate the product tier update
        if new_product_tier is not None:
            # non-free tiers require a valid payment method
            if new_product_tier.paid and not payment_method_available():
                raise NotAllowed("You must have a payment method to use non-free tiers")

        # validate the payment method update
        if new_payment_method is not None:
            # the payment method must be assigned to the workspace
            if new_payment_method not in workspace_payment_methods.available:
                raise NotAllowed("The payment method is not available for this workspace")

            # removing the payment method is not allowed for non-free tiers
            if new_payment_method is PaymentMethods.NoPaymentMethod() and current_tier.paid:
                raise NotAllowed("Cannot remove payment method for non-free tiers, downgrade the tier first")

        async def update_payment_method(payment_method: PaymentMethod) -> Workspace:
            if payment_method == workspace_payment_methods.current:
                return workspace
            match payment_method:
                case PaymentMethods.AwsSubscription(subscription_id):
                    return await self.workspace_repository.update_subscription(workspace.id, subscription_id)
                case PaymentMethods.StripeSubscription(subscription_id):
                    return await self.workspace_repository.update_subscription(workspace.id, subscription_id)
                case PaymentMethods.NoPaymentMethod():
                    return await self.workspace_repository.update_subscription(workspace.id, None)

        async def update_product_tier(product_tier: ProductTier) -> Workspace:
            if product_tier == current_tier:
                return workspace

            updated_workspace = await self.workspace_repository.update_product_tier(
                workspace_id=workspace.id, tier=product_tier
            )
            event = ProductTierChanged(
                workspace.id,
                user.id,
                product_tier,
                product_tier.paid,
                product_tier > current_tier,
                current_tier,
            )
            await self.domain_event_sender.publish(event)
            return updated_workspace

        # update the payment method
        if new_payment_method:
            workspace = await update_payment_method(new_payment_method)

        # update the product tier
        if new_product_tier:
            workspace = await update_product_tier(new_product_tier)

        return workspace

    async def create_billing_entry(
        self, subscription: SubscriptionMethod, now: Optional[datetime] = None
    ) -> Optional[BillingEntry]:
        if not subscription.active:
            log.info(f"AWS Marketplace: subscription {subscription.id} is not active")
            return None
        try:
            billing_time = now or utc()

            next_charge = start_of_next_period(period=self.billing_period, current_time=billing_time, hour=9)
            match self.billing_period:
                case "month":
                    billing_period_value = timedelta(days=30)
                case "day":
                    billing_period_value = timedelta(days=1)

            last_charged = subscription.last_charge_timestamp or billing_time
            kind = subscription.__class__.__name__

            month_factor = compute_billing_period_factor(
                billing_time=billing_time,
                last_charged=last_charged,
                period_value=billing_period_value,
            )
            workspaces = await self.workspace_repository.list_workspaces_by_subscription_id(subscription.id)

            for workspace in workspaces:
                # Get the summaries for the last period, with at least 100 resources collected and at least 3 collects
                summaries = [
                    summary
                    async for summary in self.metering_repository.collect_summary(
                        workspace.id,
                        start=last_charged,
                        end=billing_time,
                        min_resources_collected=100,
                        min_nr_of_collects=3,
                    )
                ]

                tiers = [summary.product_tier for summary in summaries]
                # highest recorded tier
                product_tier = max(tiers, default=ProductTier.Free)
                # We only count the number of accounts, no matter how many runs we had
                usage = int(len(summaries) * month_factor)
                on_payment_free_tier = product_tier.paid is False
                if on_payment_free_tier or usage == 0:
                    log.info(f"{kind}: subscription {subscription.id} has no usage")
                    # move the charge timestamp tp
                    await self.subscription_repository.update_charge_timestamp(
                        subscription.id, billing_time, next_charge
                    )
                    return None

                log.info(f"{kind}: subscription {subscription.id} collected {usage} times: {summaries}")
                AccountsCharged.labels(product_tier=product_tier.value).inc(usage)
                billing_entry = await self.subscription_repository.add_billing_entry(
                    subscription.id,
                    workspace.id,
                    product_tier,
                    usage,
                    last_charged,
                    billing_time,
                    next_charge,
                )
                await self.domain_event_sender.publish(
                    BillingEntryCreated(workspace.id, subscription.id, product_tier, usage)
                )
                return billing_entry
            else:
                log.info(f"{kind}: subscription {subscription.id} has no workspace")
                return None
        except Exception:
            log.error("Could not create a billing entry", exc_info=True)
            raise


def get_billing_entry_service(fix_dependency: FixDependency) -> BillingEntryService:
    return fix_dependency.service(ServiceNames.billing_entry_service, BillingEntryService)


BillingEntryServiceDependency = Annotated[BillingEntryService, Depends(get_billing_entry_service)]
