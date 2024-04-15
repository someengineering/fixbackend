#  Copyright (c) 2024. Some Engineering
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
import time
from datetime import timedelta
from typing import Dict, List, Annotated, Optional

import stripe
from async_lru import alru_cache
from fastapi import Depends
from fixcloudutils.asyncio.async_extensions import run_async
from fixcloudutils.service import Service
from fixcloudutils.util import utc, value_in_path
from stripe import Webhook

from fixbackend.auth.user_repository import UserRepository
from fixbackend.config import Config
from fixbackend.dependencies import FixDependency, ServiceNames
from fixbackend.domain_events.events import SubscriptionCreated
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.ids import BillingPeriod, StripeCustomerId, SubscriptionId
from fixbackend.subscription.models import StripeSubscription
from fixbackend.subscription.subscription_repository import StripeCustomerRepository, SubscriptionRepository
from fixbackend.types import AsyncSessionMaker
from fixbackend.utils import start_of_next_period, uid
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository

log = logging.getLogger(__name__)


class StripeClient:
    def __init__(self, api_key: str) -> None:
        stripe.api_key = api_key

    async def create_customer(self, email: str) -> stripe.Customer:
        return await stripe.Customer.create_async(email=email)

    async def create_subscription(
        self, customer_id: StripeCustomerId, payment_method_id: str, billing_period: BillingPeriod
    ) -> stripe.Subscription:
        # Get the money two days after the next billing period.
        # Usage is reported on 1.th - charged on 3.th
        subscription_at = start_of_next_period(period=billing_period) + timedelta(days=2)
        price_ids_by_product_id = await self.get_price_ids_by_product_id()
        return await stripe.Subscription.create_async(
            customer=customer_id,
            items=[{"price": price} for price in price_ids_by_product_id.values()],
            billing_cycle_anchor=int(time.mktime(subscription_at.timetuple())),
            # automatic_tax=dict(enabled=True),
            default_payment_method=payment_method_id,
        )

    async def create_usage_record(self, subscription_id: str, quantity: Dict[str, int]) -> List[stripe.UsageRecord]:
        price_ids_by_product_id = await self.get_price_ids_by_product_id()
        used = {price_ids_by_product_id[name]: value for name, value in quantity.items() if value > 0}
        subscription = await stripe.Subscription.retrieve_async(subscription_id)
        now = int(time.time())
        result = []
        # we will create usage records for all prices
        for item in subscription["items"]["data"]:
            plan_id = item["plan"]["id"]
            usage_record = await run_async(
                stripe.UsageRecord.create,
                subscription_item=item["id"],
                quantity=used.get(plan_id, 0),
                timestamp=now,
                action="set",
            )
            result.append(usage_record)
        return result

    async def refund(self, payment_intent_id: str) -> stripe.Refund:
        return await stripe.Refund.create_async(payment_intent=payment_intent_id)

    async def activation_price_id(self) -> str:
        prices = await self.get_prices()
        for p in prices:
            if p.lookup_key == "activation" and p.recurring is None:
                return p.id
        raise ValueError("No activation price found!")

    async def get_price_ids_by_product_id(self) -> Dict[str, str]:
        prices = await self.get_prices()
        return {p.product.name: p.id for p in prices if p.recurring is not None}  # type: ignore

    @alru_cache(ttl=600)
    async def get_prices(self) -> List[stripe.Price]:
        prices = await stripe.Price.list_async(expand=["data.product"], active=True)
        return list(prices.auto_paging_iter())


class StripeService(Service):
    async def redirect_to_stripe(self, workspace: Workspace, return_url: str) -> str:
        raise NotImplementedError("No payment service configured.")

    async def handle_event(self, event: str, signature: str) -> None:
        raise NotImplementedError("No payment service configured.")


class NoStripeService(StripeService):
    pass


class StripeServiceImpl(StripeService):
    def __init__(
        self,
        api_key: str,
        webhook_key: str,
        billing_period: BillingPeriod,
        user_repo: UserRepository,
        subscription_repository: SubscriptionRepository,
        workspace_repository: WorkspaceRepository,
        session_maker: AsyncSessionMaker,
        domain_event_publisher: DomainEventPublisher,
    ) -> None:
        self.client = StripeClient(api_key)
        self.webhook_key = webhook_key
        self.billing_period = billing_period
        self.user_repo = user_repo
        self.subscription_repository = subscription_repository
        self.workspace_repository = workspace_repository
        self.domain_event_publisher = domain_event_publisher
        self.stripe_customer_repo = StripeCustomerRepository(session_maker)

    async def redirect_to_stripe(self, workspace: Workspace, return_url: str) -> str:
        customer_id = await self._get_stripe_customer_id(workspace)
        subscription = await self._get_stripe_subscription_id(customer_id)
        if subscription is None:
            # No subscription yet: let the user create a one-time payment as activation.
            # Once the activation is done, we will create a subscription from the provided payment method.
            co_session = await stripe.checkout.Session.create_async(
                payment_method_types=["card"],
                mode="payment",
                customer=customer_id,
                success_url=f"{return_url}?success=true",
                cancel_url=f"{return_url}?success=false",
                payment_intent_data=dict(
                    setup_future_usage="off_session",  # we want to use this payment method for future payments
                    metadata=dict(reason="activation"),  # mark this payment to be refunded
                ),
                line_items=[
                    {
                        "price": await self.client.activation_price_id(),
                        "quantity": 1,
                    }
                ],
            )
            url: str = co_session.url  # type: ignore
        else:
            # subscription exists: use the customer portal to review payment data and invoices
            cu_session = await stripe.billing_portal.Session.create_async(customer=customer_id, return_url=return_url)
            url = cu_session.url
        return url

    async def handle_event(self, event: str, signature: str) -> None:
        we = Webhook.construct_event(event, signature, self.webhook_key)  # type: ignore
        do = we.data.object
        log.info(f"Received Stripe event: {we.type}: {we.id}")
        match we.type:
            case "checkout.session.completed":
                customer_id = do.get("customer")
                intent_id = do.get("payment_intent")
                if customer_id and isinstance(pid := intent_id, str):
                    await self._create_stripe_subscription(StripeCustomerId(customer_id), pid)
                else:
                    log.error("Invalid checkout session event: missing customer or payment intent")
            case "payment_intent.succeeded":
                reason = value_in_path(do, ["metadata", "reason"])
                customer_id = do.get("customer")
                intent_id = do.get("id")
                # activation payments should be refunded
                if reason == "activation" and intent_id and customer_id:
                    log.info(f"Activation payment found for customer {customer_id}. Refund.")
                    await self.client.refund(intent_id)
            case "invoice.finalized":
                # we could send the invoice via email to the customer
                pass
            case "invoice.payment_failed":
                # start the dunning process
                pass
            case _:
                pass

    async def _create_stripe_subscription(self, customer_id: StripeCustomerId, payment_intent_id: str) -> None:
        # get workspace of customer:
        if workspace_id := await self.stripe_customer_repo.workspace_of_customer(customer_id):
            # lookup the payment method of the related payment intent
            payment_intent = await stripe.PaymentIntent.retrieve_async(payment_intent_id)
            pm: str = payment_intent.payment_method  # type: ignore
            # create a subscription for customer using given payment method for defined billing period
            stripe_subscription = await self.client.create_subscription(customer_id, pm, self.billing_period)
            # the subscription has been created on the stripe side
            subscription = await self.subscription_repository.create(
                StripeSubscription(
                    id=SubscriptionId(uid()),
                    customer_identifier=customer_id,
                    stripe_subscription_id=stripe_subscription.id,
                    active=True,
                    last_charge_timestamp=utc(),
                    next_charge_timestamp=start_of_next_period(period=self.billing_period, hour=9),
                )
            )
            # mark this subscription as the active one for the workspace
            workspace = await self.workspace_repository.update_subscription(workspace_id, subscription.id)
            # publish a subscription event
            event = SubscriptionCreated(workspace_id, workspace.owner_id, subscription.id, "stripe")
            await self.domain_event_publisher.publish(event)
        else:
            raise ValueError(f"Stripe customer {customer_id} has no workspace?")

    async def _get_stripe_customer_id(self, workspace: Workspace) -> StripeCustomerId:
        customer_id = await self.stripe_customer_repo.get(workspace.id)
        if customer_id is None:
            owner = await self.user_repo.get(workspace.owner_id)
            assert owner is not None, f"Workspace {workspace.id} does not have an owner?"
            customer = await self.client.create_customer(owner.email)
            customer_id = StripeCustomerId(customer.id)
            await self.stripe_customer_repo.create(workspace.id, customer_id)
        return customer_id

    async def _get_stripe_subscription_id(self, customer_id: str) -> Optional[str]:
        async for sub in self.subscription_repository.subscriptions(stripe_customer_identifier=customer_id):
            if isinstance(sub, StripeSubscription) and sub.stripe_subscription_id:
                return sub.stripe_subscription_id
        return None


def create_stripe_service(
    config: Config,
    user_repo: UserRepository,
    subscription_repository: SubscriptionRepository,
    workspace_repository: WorkspaceRepository,
    session_maker: AsyncSessionMaker,
    domain_event_publisher: DomainEventPublisher,
) -> StripeService:
    if (api_key := config.stripe_api_key) and (ws_key := config.stripe_webhook_key):
        log.info("Stripe Service configured")
        return StripeServiceImpl(
            api_key,
            ws_key,
            config.billing_period,
            user_repo,
            subscription_repository,
            workspace_repository,
            session_maker,
            domain_event_publisher,
        )
    else:
        log.info("No Stripe Service configured")
        return NoStripeService()


def get_stripe_service(deps: FixDependency) -> StripeService:
    return deps.service(ServiceNames.stripe_service, StripeService)


StripeServiceDependency = Annotated[StripeService, Depends(get_stripe_service)]
