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
from fixcloudutils.util import uuid_str
from pytest import fixture
from stripe import _APIRequestor  # type: ignore

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
        super().__init__("some dummy key")

    async def create_customer(self, email: str) -> StripeCustomerId:
        return customer_id

    async def create_subscription(
        self, customer_id: StripeCustomerId, payment_method_id: str, billing_period: BillingPeriod
    ) -> StripeSubscriptionId:
        return subscription_id

    async def create_usage_record(self, subscription_id: str, quantity: Dict[str, int]) -> List[stripe.UsageRecord]:
        return []

    async def refund(self, payment_intent_id: str) -> stripe.Refund:
        return stripe.Refund(id=refund_id)

    async def activation_price_id(self) -> str:
        return "activate_price_id"

    async def get_price_ids_by_product_id(self) -> Dict[str, str]:
        return {"Enterprise": "p1", "Business": "p2", "Plus": "p3"}

    @alru_cache(ttl=600)
    async def get_prices(self) -> List[stripe.Price]:
        return []

    async def checkout_session(self, customer: str, **params: Any) -> str:  # type: ignore
        return f"https://localhost/{customer}/checkout"

    async def billing_portal_session(self, customer: str, **params: Any) -> str:  # type: ignore
        return f"https://localhost/{customer}/billing"

    async def payment_method_id_from_intent(
        self, id: str, **params: Unpack[stripe.PaymentIntent.RetrieveParams]
    ) -> str:
        return payment_method_id


@fixture
def stripe_service(
    user_repository: UserRepository,
    subscription_repository: SubscriptionRepository,
    workspace_repository: WorkspaceRepository,
    async_session_maker: AsyncSessionMaker,
    domain_event_sender: InMemoryDomainEventPublisher,
) -> StripeServiceImpl:
    return StripeServiceImpl(
        StripeDummyClient(),
        "dummy_secret",
        "day",
        user_repository,
        subscription_repository,
        workspace_repository,
        async_session_maker,
        domain_event_sender,
    )


def event(kind: str, data: Dict[str, Any]) -> stripe.Event:
    return stripe.Event._construct_from(
        values={
            "id": uuid_str(),
            "object": "event",
            "api_version": "2024-04-10",
            "created": 1713169811,
            "type": kind,
            "data": {"object": data},
        },
        api_mode="V1",
        requestor=_APIRequestor._global_with_options(api_key="dummy_key"),
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
