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
from fixbackend.ids import SecurityTier

from fixbackend.invoices.billing_address_repository import BillingAddressRepository
from fixbackend.invoices.models import BillingAdderss, PaymentMethod
from fixbackend.invoices.service import InvoiceService
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.workspaces.models import Workspace
from fixcloudutils.util import utc
from fixbackend.auth.models import User


@pytest.mark.asyncio
async def test_list_invoices(
    billing_address_repository: BillingAddressRepository,
    subscription_repository: SubscriptionRepository,
    subscription: AwsMarketplaceSubscription,
    workspace: Workspace,
    user: User,
) -> None:
    service = InvoiceService(subscription_repository, billing_address_repository)

    now = utc().replace(microsecond=0)

    FoundatonSecurityAccountCost = 5
    await subscription_repository.add_billing_entry(
        subscription.id, workspace.id, SecurityTier.Foundational, 42, now, now, now
    )

    # no address provided
    invoices = await service.list_invoices(workspace.id)
    assert len(invoices) == 1
    invoice = invoices[0]
    assert invoice.id is not None
    assert invoice.payment_method == PaymentMethod.AwsMarketplace
    assert invoice.amount == 42 * FoundatonSecurityAccountCost
    assert invoice.currency == "USD"
    assert invoice.period_start == now
    assert invoice.period_end == now
    assert invoice.invoice_date == now
    assert invoice.accounts_charged == 42
    assert invoice.tier == SecurityTier.Foundational
    assert invoice.billing_address is None

    # add address
    billing_adderss = BillingAdderss(
        user_id=user.id,
        name="test",
        company="test_company",
        address_line_1="test_address_line_1",
        address_line_2="test_address_line_2",
        postal_code="test_postal_code",
        city="test_city",
        state="test_state",
        country="test_country",
    )
    await billing_address_repository.create_billing_address(user.id, billing_adderss)

    invoices = await service.list_invoices(workspace.id)
    assert len(invoices) == 1
    invoice = invoices[0]
    assert invoice.billing_address == billing_adderss
