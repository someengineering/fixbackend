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

import uuid

import pytest

from fixbackend.ids import UserId
from fixbackend.invoices.billing_address_repository import BillingAddressRepository
from fixbackend.invoices.models import BillingAdderss
from fixbackend.types import AsyncSessionMaker


@pytest.mark.asyncio
async def test_create_billing_address(async_session_maker: AsyncSessionMaker) -> None:
    repo = BillingAddressRepository(session_maker=async_session_maker)
    address = BillingAdderss(
        user_id=UserId(uuid.uuid4()),
        name="test",
        company="test_company",
        address_line_1="test_address_line_1",
        address_line_2="test_address_line_2",
        postal_code="test_postal_code",
        city="test_city",
        state="test_state",
        country="test_country",
    )
    result = await repo.create_billing_address(address.user_id, address)
    assert result == address

    updated = BillingAdderss(
        user_id=address.user_id,
        name="test2",
        company="test_company2",
        address_line_1="test_address_line_12",
        address_line_2="test_address_line_22",
        postal_code="test_postal_code2",
        city="test_city2",
        state="test_state2",
        country="test_country2",
    )
    result = await repo.update_billing_address(address.user_id, updated)
    assert result == updated

    get_result = await repo.get_billing_address(address.user_id)
    assert get_result == updated

    list_result = await repo.list_billing_addresses([address.user_id])
    assert list_result == [updated]
