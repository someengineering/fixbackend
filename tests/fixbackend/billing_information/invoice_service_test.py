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

from fixbackend.billing_information.service import BillingEntryService
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.workspaces.models import Workspace
from fixcloudutils.util import utc
from fixbackend.auth.models import User


@pytest.mark.asyncio
async def test_list_billing_entries(
    subscription_repository: SubscriptionRepository,
    subscription: AwsMarketplaceSubscription,
    workspace: Workspace,
    user: User,
) -> None:
    service = BillingEntryService(subscription_repository)

    now = utc().replace(microsecond=0)

    await subscription_repository.add_billing_entry(
        subscription.id, workspace.id, SecurityTier.Foundational, 42, now, now, now
    )

    # no address provided
    invoices = await service.list_billing_info(workspace.id)
    assert len(invoices) == 1
    billing_entry = invoices[0]
    assert billing_entry.id is not None
    assert billing_entry.period_start == now
    assert billing_entry.period_end == now
    assert billing_entry.tier == SecurityTier.Foundational
