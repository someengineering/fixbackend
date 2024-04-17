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
import json
import logging
import time
from asyncio import Semaphore, TaskGroup
from datetime import timedelta
from typing import Dict, List, Annotated, Optional, Unpack

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
from fixbackend.ids import (
    BillingPeriod,
    StripeCustomerId,
    SubscriptionId,
    StripeSubscriptionId,
    ProductTier,
    WorkspaceId,
)
from fixbackend.subscription.models import StripeSubscription, BillingEntry
from fixbackend.subscription.subscription_repository import StripeCustomerRepository, SubscriptionRepository
from fixbackend.types import AsyncSessionMaker
from fixbackend.utils import start_of_next_period, uid
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository

log = logging.getLogger(__name__)

# EU countries
EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}  # fmt: skip # noqa: E501
# Countries accepting reverse-charge
REVERSE_CHARGE = EU | {"IS", "LI", "NO", "CH", "GB", "AU", "CA", "IN", "NZ", "SG", "ZA", "AE", "JP"}


class StripeClient:  # pragma: no cover
    def __init__(self, api_key: str) -> None:
        stripe.api_key = api_key

    async def create_customer(
        self, workspace_id: WorkspaceId, **params: Unpack[stripe.Customer.CreateParams]
    ) -> StripeCustomerId:
        params["metadata"] = {**params.get("metadata", {}), "workspace_id": workspace_id}  # type: ignore
        customer = await stripe.Customer.create_async(**params)
        return StripeCustomerId(customer.id)

    async def create_subscription(
        self, customer_id: StripeCustomerId, payment_method_id: str, billing_period: BillingPeriod
    ) -> StripeSubscriptionId:
        # Get the money two days after the next billing period.
        # Usage is reported on 1st - charged on 3rd
        subscription_at = start_of_next_period(period=billing_period) + timedelta(days=2)
        price_ids_by_product_id = await self.get_price_ids_by_product_id()
        subscription = await stripe.Subscription.create_async(
            customer=customer_id,
            items=[{"price": price} for price in price_ids_by_product_id.values()],
            billing_cycle_anchor=int(time.mktime(subscription_at.timetuple())),
            # automatic_tax=dict(enabled=True),
            default_payment_method=payment_method_id,
        )
        return StripeSubscriptionId(subscription.id)

    async def create_usage_record(
        self, subscription_id: str, tier: ProductTier, nr_of_accounts: int, nr_of_seats: int
    ) -> int:
        # price ids reflect the product tier, price for seat is called "Seat"
        quantity = {tier: nr_of_accounts, "Seat": nr_of_seats}
        price_ids_by_product_id = await self.get_price_ids_by_product_id()
        used = {price_ids_by_product_id[name]: value for name, value in quantity.items() if value > 0}
        subscription = await stripe.Subscription.retrieve_async(subscription_id)
        now = int(time.time())
        result = []
        # We will create multiple usage records: one for each price item
        # Reasoning: the usage has "set" mechanics - the latest reported usage overrides a previously defined one.
        # By reporting all usages of all prices, the complete state is updated.
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
        return len(result)

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

    async def checkout_session(self, **params: Unpack[stripe.checkout.Session.CreateParams]) -> str:
        session = await stripe.checkout.Session.create_async(**params)
        assert session.url is not None, "No session URL?"
        return session.url

    async def billing_portal_session(self, **params: Unpack[stripe.billing_portal.Session.CreateParams]) -> str:
        session = await stripe.billing_portal.Session.create_async(**params)
        return session.url

    async def update_customer(self, cid: StripeCustomerId, **params: Unpack[stripe.Customer.ModifyParams]) -> None:
        await stripe.Customer.modify_async(cid, **params)

    async def payment_method_id_from_intent(
        self, id: str, **params: Unpack[stripe.PaymentIntent.RetrieveParams]
    ) -> str:
        intent = await stripe.PaymentIntent.retrieve_async(id, **params)
        return intent.payment_method  # type: ignore

    @alru_cache(ttl=600)
    async def get_prices(self) -> List[stripe.Price]:
        prices = await stripe.Price.list_async(expand=["data.product"], active=True)
        return list(prices.auto_paging_iter())


class StripeService(Service):
    async def redirect_to_stripe(self, workspace: Workspace, return_url: str) -> str:
        raise NotImplementedError("No payment service configured.")

    async def handle_event(self, event: str, signature: str) -> None:
        raise NotImplementedError("No payment service configured.")

    async def report_unreported_usages(self) -> int:
        raise NotImplementedError("No payment service configured.")


class NoStripeService(StripeService):
    pass


class StripeServiceImpl(StripeService):
    def __init__(
        self,
        client: StripeClient,
        webhook_key: str,
        billing_period: BillingPeriod,
        user_repo: UserRepository,
        subscription_repo: SubscriptionRepository,
        workspace_repo: WorkspaceRepository,
        session_maker: AsyncSessionMaker,
        domain_event_publisher: DomainEventPublisher,
    ) -> None:
        self.client = client
        self.webhook_key = webhook_key
        self.billing_period = billing_period
        self.user_repo = user_repo
        self.subscription_repository = subscription_repo
        self.workspace_repository = workspace_repo
        self.domain_event_publisher = domain_event_publisher
        self.stripe_customer_repo = StripeCustomerRepository(session_maker)

    async def redirect_to_stripe(self, workspace: Workspace, return_url: str) -> str:
        customer_id = await self._get_stripe_customer_id(workspace)
        subscription = await self._get_stripe_subscription_id(customer_id)
        if subscription is None:
            # No subscription yet: let the user create a one-time payment as activation.
            # Once the activation is done, we will create a subscription from the provided payment method.
            url = await self.client.checkout_session(
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
                customer_update=dict(name="auto", address="auto"),  # is allowed to update customer data
                automatic_tax=dict(enabled=False),  # no tax for this item, the money will be refunded immediately
                invoice_creation=dict(enabled=False),  # we do not want to create an invoice for this item
                billing_address_collection="required",  # we need the billing address for the subscription
                custom_fields=[  # allow definition of the company name (will become the customer name)
                    dict(key="company", label=dict(type="custom", custom="Company"), optional=False, type="text"),
                ],
                consent_collection=dict(  # we need the consent to store the payment method
                    payment_method_reuse_agreement=dict(position="auto"), terms_of_service="required"
                ),
                submit_type="book",  # the button text to order
            )
        else:
            # subscription exists: use the customer portal to review payment data and invoices
            url = await self.client.billing_portal_session(customer=customer_id, return_url=return_url)
        return url

    async def report_unreported_usages(self, raise_exception: bool = False) -> int:
        async def send(be: BillingEntry, subscription: StripeSubscription) -> None:
            try:
                await self.client.create_usage_record(
                    subscription.stripe_subscription_id, be.tier, be.nr_of_accounts_charged, nr_of_seats=0
                )
                await self.subscription_repository.mark_billing_entry_reported(entry.id)
            except Exception:
                log.error(f"Could not report usage for billing entry {be.id}", exc_info=True)
                if raise_exception:
                    raise

        counter = 0
        max_concurrent = Semaphore(64)  # up to 64 concurrent tasks
        async with TaskGroup() as group:
            async for entry, subscription in self.subscription_repository.unreported_stripe_billing_entries():
                counter += 1
                async with max_concurrent:
                    await group.create_task(send(entry, subscription))
        return counter

    async def handle_event(self, event: str, signature: str) -> None:  # pragma: no cover
        # This will validate the event using the secret key you provided
        if log.isEnabledFor(logging.DEBUG):
            log.debug("Stripe event: %s", json.dumps(json.loads(event), indent=2))
        await self.handle_verified_event(Webhook.construct_event(event, signature, self.webhook_key))  # type: ignore

    async def handle_verified_event(self, event: stripe.Event) -> None:
        do = event.data.object
        log.info(f"Received Stripe event: {event.type}: {event.id}")
        match event.type:
            case "checkout.session.completed":
                cid = do.get("customer")
                intent_id = do.get("payment_intent")
                custom_fields = {f["key"]: value_in_path(f, ["text", "value"]) for f in do.get("custom_fields", [])}
                company = custom_fields.get("company")
                country_code = value_in_path(do, ["customer_details", "address", "country"])
                # Update the customer: set company name and tax_exemption based on country code
                if cid and company and country_code:
                    await self._update_customer(StripeCustomerId(cid), company=company, country_code=country_code)
                # Create a subscription for the customer
                if cid and isinstance(pid := intent_id, str):
                    await self._create_stripe_subscription(StripeCustomerId(cid), pid)
                else:
                    log.error("Invalid checkout session event: missing customer or payment intent")
            case "payment_intent.succeeded":
                reason = value_in_path(do, ["metadata", "reason"])
                cid = do.get("customer")
                intent_id = do.get("id")
                # activation payments should be refunded
                if reason == "activation" and intent_id and cid:
                    log.info(f"Activation payment found for customer {cid}. Refund.")
                    await self.client.refund(intent_id)
            case "customer.updated":
                # check if country has changed, which might involve a change in tax settings
                cid = do.get("customer")
                country_changed = value_in_path(do, ["previous_attributes", "address", "country"])
                country = value_in_path(do, ["address", "country"])
                if cid and country_changed and country:
                    await self._update_customer(StripeCustomerId(cid), country_code=country)
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
            # idempotency: do nothing if we already have an active stripe subscription
            if (ws := await self.workspace_repository.get_workspace(workspace_id)) and ws.subscription_id:
                existing = await self.subscription_repository.get_subscription(ws.subscription_id)
                if isinstance(existing, StripeSubscription) and existing.active:
                    log.info(f"Workspace {workspace_id} already has a stripe subscription {existing.id}")
                    return
            # lookup the payment method of the related payment intent
            pm_id = await self.client.payment_method_id_from_intent(payment_intent_id)
            # create a subscription for customer using given payment method for defined billing period
            stripe_subscription = await self.client.create_subscription(customer_id, pm_id, self.billing_period)
            # the subscription has been created on the stripe side
            subscription = await self.subscription_repository.create(
                StripeSubscription(
                    id=SubscriptionId(uid()),
                    customer_identifier=customer_id,
                    stripe_subscription_id=stripe_subscription,
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

    async def _update_customer(
        self, cid: StripeCustomerId, *, company: Optional[str] = None, country_code: Optional[str] = None
    ) -> None:
        update = {}
        if company:
            update["name"] = company
        if country_code and country_code.upper() in REVERSE_CHARGE:  # set reverse-charge if the country accepts it
            update["tax_exempt"] = "reverse"
        if country_code and country_code.upper() == "US":  # unset any value if the country is US
            update["tax_exempt"] = "none"
        if update:
            await self.client.update_customer(cid, **update)  # type: ignore

    async def _get_stripe_customer_id(self, workspace: Workspace) -> StripeCustomerId:
        customer_id = await self.stripe_customer_repo.get(workspace.id)
        if customer_id is None:
            owner = await self.user_repo.get(workspace.owner_id)
            assert owner is not None, f"Workspace {workspace.id} does not have an owner?"
            customer_id = await self.client.create_customer(workspace.id, email=owner.email)
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
        client = StripeClient(api_key)
        return StripeServiceImpl(
            client,
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
