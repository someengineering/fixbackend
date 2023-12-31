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
from fixbackend.ids import SecurityTier
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository
from fixbackend.errors import NotAllowed


@pytest.mark.asyncio
async def test_list_billing_entries(
    subscription_repository: SubscriptionRepository,
    workspace_repository: WorkspaceRepository,
    subscription: AwsMarketplaceSubscription,
    workspace: Workspace,
    user: User,
) -> None:
    service = BillingEntryService(subscription_repository, workspace_repository)

    now = utc().replace(microsecond=0)

    await subscription_repository.add_billing_entry(
        subscription.id, workspace.id, SecurityTier.Foundational, 42, now, now, now
    )

    # no address provided
    billing_info = await service.list_billing_info(workspace.id)
    assert len(billing_info) == 1
    billing_entry = billing_info[0]
    assert billing_entry.id is not None
    assert billing_entry.period_start == now
    assert billing_entry.period_end == now
    assert billing_entry.tier == SecurityTier.Foundational


@pytest.mark.asyncio
async def test_list_payment_methods(
    subscription_repository: SubscriptionRepository,
    workspace_repository: WorkspaceRepository,
    subscription: AwsMarketplaceSubscription,
    workspace: Workspace,
    user: User,
) -> None:
    service = BillingEntryService(subscription_repository, workspace_repository)

    # we're on the free tier:
    assert workspace.security_tier == SecurityTier.Free
    available_methods = await service.get_payment_methods(workspace, user.id)
    match available_methods.current:
        case PaymentMethods.AwsSubscription(subscription_id):
            assert subscription_id == subscription.id
        case _:
            assert False, "Expected aws_marketplace payment method"
    assert len(available_methods.available) == 1
    match available_methods.available[0]:
        case PaymentMethods.NoPaymentMethod():
            pass
        case _:
            assert False, "Expected no_payment_method payment method"

    # on paid tier we can't get the no payment method
    assert workspace.security_tier == SecurityTier.Free
    workspace = await workspace_repository.update_security_tier(workspace.id, SecurityTier.Foundational)
    available_methods = await service.get_payment_methods(workspace, user.id)
    match available_methods.current:
        case PaymentMethods.AwsSubscription(subscription_id):
            assert subscription_id == subscription.id
        case _:
            assert False, "Expected aws_marketplace payment method"
    assert len(available_methods.available) == 0


@pytest.mark.asyncio
async def test_update_billing(
    subscription_repository: SubscriptionRepository,
    workspace_repository: WorkspaceRepository,
    subscription: AwsMarketplaceSubscription,
    workspace: Workspace,
    user: User,
) -> None:
    service = BillingEntryService(subscription_repository, workspace_repository)

    # we're on the free tier:
    assert workspace.security_tier == SecurityTier.Free
    # update to higher tier is possible if there is a payment method
    workspace = await service.update_billing(workspace, new_security_tier=SecurityTier.Foundational)
    assert workspace.security_tier == SecurityTier.Foundational

    # removing the payment method on non-free tier is not possible
    with pytest.raises(NotAllowed):
        await service.update_billing(workspace, new_payment_method=PaymentMethods.NoPaymentMethod())

    # downgrading to free is possible
    workspace = await service.update_billing(workspace, new_security_tier=SecurityTier.Free)
    assert workspace.security_tier == SecurityTier.Free

    # we can remove the payment method if we're on free tier
    workspace = await service.update_billing(workspace, new_payment_method=PaymentMethods.NoPaymentMethod())
    payment_methods = await service.get_payment_methods(workspace, user.id)
    assert payment_methods.current == PaymentMethods.NoPaymentMethod()

    # upgrading to paid tier is not possible without payment method
    with pytest.raises(NotAllowed):
        await service.update_billing(workspace, new_security_tier=SecurityTier.Foundational)

    # but if we add the payment then we can upgrade to a paid plan
    workspace = await service.update_billing(
        workspace,
        new_payment_method=PaymentMethods.AwsSubscription(subscription.id),
        new_security_tier=SecurityTier.HighSecurity,
    )
    assert workspace.security_tier == SecurityTier.HighSecurity
