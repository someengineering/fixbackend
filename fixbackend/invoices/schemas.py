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
from typing import Optional
from fixbackend.ids import BillingId

from pydantic import BaseModel, Field
from pydantic_extra_types.country import CountryAlpha2


from fixbackend.invoices.models import BillingAdderss, Invoice


class InvoiceRead(BaseModel):
    id: BillingId = Field(description="The invoice's unique identifier")
    date: datetime = Field(description="Date of the invoice")
    amount: Decimal = Field(description="The amount of the invoice")
    currency: str = Field(description="The currency of the invoice")
    invoice_pdf_url: Optional[str] = Field(description="The URL of the invoice PDF for downloading")

    @staticmethod
    def from_model(invoice: Invoice) -> "InvoiceRead":
        return InvoiceRead(
            id=invoice.id,
            date=invoice.invoice_date,
            amount=invoice.amount,
            currency=invoice.currency,
            invoice_pdf_url=None,
        )


class BillingAddressJson(BaseModel):
    name: str = Field(max_length=256, description="The name of the billing address")
    company: Optional[str] = Field(max_length=256, description="The company of the billing address")
    address_line_1: str = Field(max_length=256, description="The first line of the billing address")
    address_line_2: str = Field(max_length=256, description="The second line of the billing address")
    postal_code: str = Field(max_length=256, description="The postal code of the billing address")
    city: str = Field(max_length=256, description="The city of the billing address")
    state: str = Field(max_length=256, description="The state of the billing address")
    country: CountryAlpha2 = Field(description="The country of the billing address")

    @staticmethod
    def from_model(billing_address: BillingAdderss) -> "BillingAddressJson":
        return BillingAddressJson(
            name=billing_address.name,
            company=billing_address.company,
            address_line_1=billing_address.address_line_1,
            address_line_2=billing_address.address_line_2,
            postal_code=billing_address.postal_code,
            city=billing_address.city,
            state=billing_address.state,
            country=CountryAlpha2(billing_address.country),
        )
