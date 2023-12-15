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


from decimal import Decimal
from typing import Annotated, List, Optional, Set, Tuple

from fastapi import Depends

from fixbackend.ids import SecurityTier, UserId, WorkspaceId
from fixbackend.invoices.models import Invoice
from fixbackend.subscription.models import BillingEntry
from fixbackend.subscription.subscription_repository import SubscriptionRepository, SubscriptionRepositoryDependency
from fixbackend.invoices.billing_address_repository import BillingAddressRepository, BillingAddressRepositoryDependency


class InvoiceService:
    def __init__(
        self, subscription_repository: SubscriptionRepository, billing_address_repository: BillingAddressRepository
    ) -> None:
        self.subscription_repository = subscription_repository
        self.billing_address_repository = billing_address_repository
        # todo: sync pricing from AWS Marketplace
        self.price_per_tier = {
            SecurityTier.Free: Decimal(0),
            SecurityTier.Foundational: Decimal(5),
            SecurityTier.HighSecurity: Decimal(50),
        }

    async def list_invoices(self, workspace_id: WorkspaceId) -> List[Invoice]:
        billing_entries: List[Tuple[BillingEntry, Optional[UserId]]] = []
        user_ids: Set[UserId] = set()
        async for billing, subscription in self.subscription_repository.list_billing_for_workspace(workspace_id):
            billing_entries.append((billing, subscription.user_id))
            if subscription.user_id:
                user_ids.add(subscription.user_id)
        billing_addresses = {
            address.user_id: address
            for address in await self.billing_address_repository.list_billing_addresses(list(user_ids))
        }
        return [
            Invoice.from_billing_entry(entry, self.price_per_tier, billing_addresses.get(user_id) if user_id else None)
            for entry, user_id in billing_entries
        ]


def get_invoice_service(
    subscription_repository: SubscriptionRepositoryDependency,
    billing_address_repository: BillingAddressRepositoryDependency,
) -> InvoiceService:
    return InvoiceService(subscription_repository, billing_address_repository)


InvoiceServiceDependency = Annotated[InvoiceService, Depends(get_invoice_service)]
