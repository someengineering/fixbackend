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

import pytest
from fixcloudutils.util import utc

from fixbackend.auth.models import User
from fixbackend.billing_information.models import PaymentMethods
from fixbackend.billing_information.service import BillingEntryService
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.ids import ProductTier
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository
from fixbackend.errors import NotAllowed


@pytest.fixture
async def billing_entry_service(
    subscription_repository: SubscriptionRepository,
    workspace_repository: WorkspaceRepository,
    domain_event_sender: DomainEventPublisher,
) -> BillingEntryService:
    return BillingEntryService(subscription_repository, workspace_repository, domain_event_sender)


@pytest.mark.asyncio
async def test_list_billing_entries(
    billing_entry_service: BillingEntryService,
    subscription_repository: SubscriptionRepository,
    subscription: AwsMarketplaceSubscription,
    workspace: Workspace,
    user: User,
) -> None:

    now = utc().replace(microsecond=0)

    await subscription_repository.add_billing_entry(subscription.id, workspace.id, ProductTier.Plus, 42, now, now, now)

    # no address provided
    billing_info = await billing_entry_service.list_billing_info(workspace.id)
    assert len(billing_info) == 1
    billing_entry = billing_info[0]
    assert billing_entry.id is not None
    assert billing_entry.period_start == now
    assert billing_entry.period_end == now
    assert billing_entry.tier == ProductTier.Plus


@pytest.mark.asyncio
async def test_list_payment_methods(
    billing_entry_service: BillingEntryService,
    workspace_repository: WorkspaceRepository,
    subscription: AwsMarketplaceSubscription,
    workspace: Workspace,
    user: User,
) -> None:

    # we're on the free tier and have no subscription attached:
    assert workspace.product_tier == ProductTier.Free
    available_methods = await billing_entry_service.get_payment_methods(workspace, user.id)
    match available_methods.current:
        case PaymentMethods.NoPaymentMethod():
            assert True
        case _:
            assert False, "Expected no payment method available"
    assert len(available_methods.available) == 2
    assert available_methods.available[0] == PaymentMethods.NoPaymentMethod()
    match available_methods.available[1]:
        case PaymentMethods.AwsSubscription(subscription_id):
            assert subscription_id == subscription.id
        case _:
            assert False, "Expected subscription to be available payment method"

    await workspace_repository.update_subscription(workspace.id, subscription.id)

    # on paid tier we can't get the no payment method
    assert workspace.product_tier == ProductTier.Free
    workspace = await workspace_repository.update_product_tier(workspace.id, ProductTier.Plus)
    available_methods = await billing_entry_service.get_payment_methods(workspace, user.id)
    match available_methods.current:
        case PaymentMethods.AwsSubscription(subscription_id):
            assert subscription_id == subscription.id
        case _:
            assert False, "Expected aws_marketplace payment method"
    assert len(available_methods.available) == 1
    assert available_methods.available[0] == PaymentMethods.AwsSubscription(subscription.id)


@pytest.mark.asyncio
async def test_update_billing(
    subscription: AwsMarketplaceSubscription,
    billing_entry_service: BillingEntryService,
    workspace: Workspace,
    workspace_repository: WorkspaceRepository,
    user: User,
) -> None:
    # we're on the free tier:
    assert workspace.product_tier == ProductTier.Free
    # update to higher tier is possible if there is a payment method
    await workspace_repository.update_subscription(workspace.id, subscription.id)
    workspace = await billing_entry_service.update_billing(user, workspace, new_product_tier=ProductTier.Plus)
    assert workspace.product_tier == ProductTier.Plus

    # removing the payment method on non-free tier is not possible
    with pytest.raises(NotAllowed):
        await billing_entry_service.update_billing(user, workspace, new_payment_method=PaymentMethods.NoPaymentMethod())

    # downgrading to free is possible
    workspace = await billing_entry_service.update_billing(user, workspace, new_product_tier=ProductTier.Free)
    assert workspace.product_tier == ProductTier.Free

    # we can remove the payment method if we're on free tier
    workspace = await billing_entry_service.update_billing(
        user, workspace, new_payment_method=PaymentMethods.NoPaymentMethod()
    )
    payment_methods = await billing_entry_service.get_payment_methods(workspace, user.id)
    assert payment_methods.current == PaymentMethods.NoPaymentMethod()

    # upgrading to paid tier is not possible without payment method
    with pytest.raises(NotAllowed):
        await billing_entry_service.update_billing(user, workspace, new_product_tier=ProductTier.Plus)

    # but if we add the payment then we can upgrade to a paid plan
    workspace = await billing_entry_service.update_billing(
        user,
        workspace,
        new_payment_method=PaymentMethods.AwsSubscription(subscription.id),
        new_product_tier=ProductTier.Business,
    )
    assert workspace.product_tier == ProductTier.Business
