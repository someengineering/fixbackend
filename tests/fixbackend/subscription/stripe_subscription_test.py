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
from datetime import timedelta
from typing import Dict, Any

import stripe
from fixcloudutils.util import uuid_str, utc

from fixbackend.ids import SubscriptionId, ProductTier
from fixbackend.subscription.models import StripeSubscription
from fixbackend.subscription.stripe_subscription import StripeServiceImpl
from fixbackend.utils import uid
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepositoryImpl
from tests.fixbackend.conftest import (
    stripe_customer_id,
    stripe_payment_intent_id,
    StripeDummyClient,
    stripe_subscription_id,
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
    redirect = await stripe_service.redirect_to_stripe(workspace, "https://localhost/return", None)
    assert redirect.endswith("checkout")
    assert await stripe_service.stripe_customer_repo.get(workspace.id) is not None
    # the same customer should be redirected to the same checkout
    redirect2 = await stripe_service.redirect_to_stripe(workspace, "https://localhost/return", None)
    assert redirect == redirect2
    # send event that the customer bough a subscription
    await stripe_service.handle_verified_event(
        event(
            "checkout.session.completed", {"customer": stripe_customer_id, "payment_intent": stripe_payment_intent_id}
        )
    )
    # now the customer is redirected to the billing portal
    redirect = await stripe_service.redirect_to_stripe(workspace, "https://localhost/return", None)
    assert redirect.endswith("billing")


async def test_redirect_to_stripe_with_product_tier(
    stripe_service: StripeServiceImpl, workspace: Workspace, workspace_repository: WorkspaceRepositoryImpl
) -> None:
    # new customers need to enter payment data
    assert await stripe_service.stripe_customer_repo.get(workspace.id) is None
    redirect = await stripe_service.redirect_to_stripe(workspace, "https://localhost/return", ProductTier.Business)
    assert redirect.endswith("checkout")
    assert await stripe_service.stripe_customer_repo.get(workspace.id) is not None
    # we stored the desired product tier in the stripe customer table
    assert await stripe_service.stripe_customer_repo.get_product_tier(workspace_id=workspace.id) == ProductTier.Business
    # the same customer should be redirected to the same checkout
    redirect2 = await stripe_service.redirect_to_stripe(workspace, "https://localhost/return", ProductTier.Business)
    assert redirect == redirect2
    # send event that the customer bough a subscription
    await stripe_service.handle_verified_event(
        event(
            "checkout.session.completed", {"customer": stripe_customer_id, "payment_intent": stripe_payment_intent_id}
        )
    )
    # now the customer is redirected to the billing portal
    redirect = await stripe_service.redirect_to_stripe(workspace, "https://localhost/return", None)
    assert redirect.endswith("billing")

    # workspace product tier is updated after the subscription is created
    updated_workspace = await workspace_repository.get_workspace(workspace.id)
    assert updated_workspace
    assert updated_workspace.current_product_tier() == ProductTier.Business


async def test_refund(stripe_service: StripeServiceImpl, stripe_client: StripeDummyClient) -> None:
    # nothing is refunded in case the payment is not annotated with reason activation
    await stripe_service.handle_verified_event(
        event(
            "payment_intent.succeeded",
            {"id": stripe_payment_intent_id, "customer": stripe_customer_id},
        )
    )
    assert len(stripe_client.requests) == 0
    # this payment is an activation payment and needs to be refunded
    await stripe_service.handle_verified_event(
        event(
            "payment_intent.succeeded",
            {"id": stripe_payment_intent_id, "customer": stripe_customer_id, "metadata": {"reason": "activation"}},
        )
    )
    assert len(stripe_client.requests) == 1
    assert stripe_client.requests[0]["call"] == "refund"


async def test_report_usage(stripe_service: StripeServiceImpl, workspace: Workspace) -> None:
    # no billing entry -> no usage is reported
    assert await stripe_service.report_unreported_usages(True) == 0

    # create subscription and billing entry: expect one usage to be reported
    subscription = await stripe_service.subscription_repository.create(
        StripeSubscription(
            SubscriptionId(uid()), workspace.id, stripe_customer_id, stripe_subscription_id, True, None, None
        )
    )
    await stripe_service.subscription_repository.add_billing_entry(
        subscription.id, workspace.id, ProductTier.Enterprise, 23, utc(), utc(), utc() + timedelta(days=1)
    )
    assert await stripe_service.report_unreported_usages(True) == 1

    # A later call does not report anything, since it has already been reported
    assert await stripe_service.report_unreported_usages(True) == 0


async def test_tax_exemption(stripe_service: StripeServiceImpl, stripe_client: StripeDummyClient) -> None:
    def move(a: str, b: str) -> stripe.Event:
        return event(
            "customer.updated",
            {
                "customer": stripe_customer_id,
                "address": {"country": b},
                "previous_attributes": {"address": {"country": a}},
            },
        )

    # moving from us to de should change the tax exemption to reverse
    await stripe_service.handle_verified_event(move("US", "DE"))
    assert len(stripe_client.requests) == 1
    assert stripe_client.requests[0]["call"] == "update_customer"
    assert stripe_client.requests[0]["tax_exempt"] == "reverse"
    stripe_client.requests.clear()
    # moving from de to us should change the tax exemption to none
    await stripe_service.handle_verified_event(move("DE", "US"))
    assert len(stripe_client.requests) == 1
    assert stripe_client.requests[0]["call"] == "update_customer"
    assert stripe_client.requests[0]["tax_exempt"] == "none"
    stripe_client.requests.clear()
    # moving from china to russia should not change the tax exemption
    await stripe_service.handle_verified_event(move("CN", "RU"))
    assert len(stripe_client.requests) == 0
