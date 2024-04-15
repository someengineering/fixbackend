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
from typing import List, Dict, Unpack, Any

import stripe
from async_lru import alru_cache
from fixcloudutils.types import Json
from fixcloudutils.util import uuid_str
from pytest import fixture

from fixbackend.auth.user_repository import UserRepository
from fixbackend.ids import StripeCustomerId, BillingPeriod, StripeSubscriptionId
from fixbackend.subscription.stripe_subscription import StripeClient, StripeServiceImpl
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.types import AsyncSessionMaker
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository
from tests.fixbackend.conftest import InMemoryDomainEventPublisher

customer_id = StripeCustomerId("dummy_customer_id")
payment_intent_id = "dummy_payment_intent_id"
payment_method_id = "dummy_payment_method_id"
subscription_id = StripeSubscriptionId("dummy_subscription_id")
refund_id = "dummy_refund_id"


class StripeDummyClient(StripeClient):
    def __init__(self) -> None:
        self.requests: List[Json] = []
        super().__init__("some dummy key")

    async def create_customer(self, email: str) -> StripeCustomerId:
        self.requests.append(dict(call="create_customer", email=email))
        return customer_id

    async def create_subscription(
        self, customer_id: StripeCustomerId, payment_method_id: str, billing_period: BillingPeriod
    ) -> StripeSubscriptionId:
        self.requests.append(
            dict(call="create_subscription", customer_id=customer_id, payment_method_id=payment_method_id)
        )
        return subscription_id

    async def create_usage_record(self, subscription_id: str, quantity: Dict[str, int]) -> List[stripe.UsageRecord]:
        self.requests.append(dict(call="create_usage_record", subscription_id=subscription_id, quantity=quantity))
        return []

    async def refund(self, payment_intent_id: str) -> stripe.Refund:
        self.requests.append(dict(call="refund", payment_intent_id=payment_intent_id))
        return stripe.Refund(id=refund_id)

    async def activation_price_id(self) -> str:
        self.requests.append(dict(call="activation_price_id"))
        return "activate_price_id"

    async def get_price_ids_by_product_id(self) -> Dict[str, str]:
        self.requests.append(dict(call="get_price_ids_by_product_id"))
        return {"Enterprise": "p1", "Business": "p2", "Plus": "p3"}

    @alru_cache(ttl=600)
    async def get_prices(self) -> List[stripe.Price]:
        self.requests.append(dict(call="get_prices"))
        return []

    async def checkout_session(self, customer: str, **params: Any) -> str:  # type: ignore
        self.requests.append(dict(call="checkout_session", customer=customer))
        return f"https://localhost/{customer}/checkout"

    async def billing_portal_session(self, customer: str, **params: Any) -> str:  # type: ignore
        self.requests.append(dict(call="billing_portal_session", customer=customer))
        return f"https://localhost/{customer}/billing"

    async def payment_method_id_from_intent(
        self, id: str, **params: Unpack[stripe.PaymentIntent.RetrieveParams]
    ) -> str:
        self.requests.append(dict(call="payment_method_id_from_intent", id=id))
        return payment_method_id


@fixture
def stripe_client() -> StripeDummyClient:
    return StripeDummyClient()


@fixture
def stripe_service(
    user_repository: UserRepository,
    subscription_repository: SubscriptionRepository,
    workspace_repository: WorkspaceRepository,
    async_session_maker: AsyncSessionMaker,
    domain_event_sender: InMemoryDomainEventPublisher,
    stripe_client: StripeDummyClient,
) -> StripeServiceImpl:
    return StripeServiceImpl(
        stripe_client,
        "dummy_secret",
        "day",
        user_repository,
        subscription_repository,
        workspace_repository,
        async_session_maker,
        domain_event_sender,
    )


def event(kind: str, data: Dict[str, Any]) -> stripe.Event:
    return stripe.Event.construct_from(
        values={
            "id": uuid_str(),
            "object": "event",
            "api_version": "2024-04-10",
            "created": 1713169811,
            "type": kind,
            "data": {"object": data},
        },
        key="dummy",
        api_mode="V1",
    )


async def test_redirect_to_stripe(stripe_service: StripeServiceImpl, workspace: Workspace) -> None:
    # new customers need to enter payment data
    assert await stripe_service.stripe_customer_repo.get(workspace.id) is None
    redirect = await stripe_service.redirect_to_stripe(workspace, "https://localhost/return")
    assert redirect.endswith("checkout")
    assert await stripe_service.stripe_customer_repo.get(workspace.id) is not None
    # the same customer should be redirected to the same checkout
    redirect2 = await stripe_service.redirect_to_stripe(workspace, "https://localhost/return")
    assert redirect == redirect2
    # send event that the customer bough a subscription
    await stripe_service.handle_verified_event(
        event("checkout.session.completed", {"customer": customer_id, "payment_intent": payment_intent_id})
    )
    # now the customer is redirected to the billing portal
    redirect = await stripe_service.redirect_to_stripe(workspace, "https://localhost/return")
    assert redirect.endswith("billing")


async def test_refund(stripe_service: StripeServiceImpl, stripe_client: StripeDummyClient) -> None:
    # nothing is refunded in case the payment is not annotated with reason activation
    await stripe_service.handle_verified_event(
        event(
            "payment_intent.succeeded",
            {"id": payment_intent_id, "customer": customer_id},
        )
    )
    assert len(stripe_client.requests) == 0
    # this payment is an activation payment and needs to be refunded
    await stripe_service.handle_verified_event(
        event(
            "payment_intent.succeeded",
            {"id": payment_intent_id, "customer": customer_id, "metadata": {"reason": "activation"}},
        )
    )
    assert len(stripe_client.requests) == 1
    assert stripe_client.requests[0]["call"] == "refund"
