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

from datetime import datetime
from decimal import Decimal
from attrs import frozen
from typing import Dict, Optional


from fixbackend.ids import BillingId, SecurityTier, UserId
from fixbackend.subscription.models import BillingEntry
from enum import Enum


class PaymentMethod(str, Enum):
    AwsMarketplace = "AwsMarketplace"


@frozen
class BillingAdderss:
    user_id: UserId
    name: str
    company: Optional[str]
    address_line_1: str
    address_line_2: str
    postal_code: str
    city: str
    state: str
    country: str


@frozen
class Invoice:
    id: BillingId
    invoice_date: datetime
    period_start: datetime
    period_end: datetime
    amount: Decimal
    currency: str
    accounts_charged: int
    tier: SecurityTier
    payment_method: PaymentMethod
    billing_address: Optional[BillingAdderss]

    @staticmethod
    def from_billing_entry(
        billing_entry: BillingEntry,
        pricing_per_tier: Dict[SecurityTier, Decimal],
        billing_address: Optional[BillingAdderss],
    ) -> "Invoice":
        tier = SecurityTier(billing_entry.tier)
        amount = billing_entry.nr_of_accounts_charged * pricing_per_tier[tier]
        return Invoice(
            id=billing_entry.id,
            invoice_date=billing_entry.period_end,
            period_start=billing_entry.period_start,
            period_end=billing_entry.period_end,
            amount=amount,
            currency="USD",
            accounts_charged=billing_entry.nr_of_accounts_charged,
            tier=tier,
            payment_method=PaymentMethod.AwsMarketplace,
            billing_address=billing_address,
        )
