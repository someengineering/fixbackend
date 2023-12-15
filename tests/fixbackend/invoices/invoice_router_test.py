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
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from fixbackend.auth.depedencies import get_current_active_verified_user
from fixbackend.auth.models import User
from fixbackend.config import Config, get_config
from typing import AsyncIterator, List, Optional
from fixbackend.app import fast_api_app
from fixbackend.db import get_async_session
from fixbackend.ids import BillingId, ExternalId, SecurityTier, UserId, WorkspaceId
from fixbackend.invoices.billing_address_repository import BillingAddressRepository, get_billing_address_repository
from fixbackend.invoices.models import BillingAdderss, Invoice, PaymentMethod
from fixbackend.invoices.schemas import BillingAddressJson
from fixbackend.invoices.service import InvoiceService, get_invoice_service
from fixbackend.workspaces.dependencies import get_user_workspace
from fixbackend.workspaces.models import Workspace
from fixcloudutils.util import utc, UTC_Date_Format

external_id = ExternalId(uuid.uuid4())
workspace_id = WorkspaceId(uuid.uuid4())
workspace = Workspace(workspace_id, "foo", "foo", external_id, [], [], SecurityTier.Free)
user_id = UserId(uuid.uuid4())
user = User(
    id=user_id,
    email="foo@example.com",
    hashed_password="passord",
    is_verified=True,
    is_active=True,
    is_superuser=False,
    oauth_accounts=[],
)

invoice = Invoice(
    id=BillingId(uuid.uuid4()),
    invoice_date=utc().replace(microsecond=0),
    period_start=utc(),
    period_end=utc(),
    amount=Decimal(42),
    currency="USD",
    accounts_charged=1,
    tier=SecurityTier.Free,
    payment_method=PaymentMethod.AwsMarketplace,
    billing_address=None,
)


class InvoiceServiceMock(InvoiceService):
    def __init__(self) -> None:
        pass

    async def list_invoices(self, workspace_id: WorkspaceId) -> List[Invoice]:
        return [invoice]


billing_address = BillingAdderss(
    user_id=user_id,
    name="name",
    company="company",
    address_line_1="address_line_1",
    address_line_2="address_line_2",
    postal_code="postal_code",
    city="city",
    state="state",
    country="US",
)


class BillingAddressRepositoryMock(BillingAddressRepository):
    def __init__(self) -> None:
        pass

    async def create_billing_address(self, user_id: UserId, billing_address: BillingAdderss) -> BillingAdderss:
        return billing_address

    async def get_billing_address(self, user_id: UserId) -> Optional[BillingAdderss]:
        return billing_address

    async def update_billing_address(self, user_id: UserId, billing_address: BillingAdderss) -> BillingAdderss:
        return billing_address


@pytest.fixture
async def client(session: AsyncSession, default_config: Config) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app = fast_api_app(default_config)

    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_config] = lambda: default_config
    app.dependency_overrides[get_user_workspace] = lambda: workspace
    app.dependency_overrides[get_current_active_verified_user] = lambda: user
    app.dependency_overrides[get_invoice_service] = lambda: InvoiceServiceMock()
    app.dependency_overrides[get_billing_address_repository] = lambda: BillingAddressRepositoryMock()

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_list_invoices(client: AsyncClient) -> None:
    response = await client.get("/api/workspaces/{workspace_id}/invoices/")
    assert response.status_code == 200
    assert len(response.json()) == 1
    json_invoice = response.json()[0]
    assert json_invoice["id"] == str(invoice.id)
    assert json_invoice["date"] == invoice.invoice_date.strftime(UTC_Date_Format)
    assert json_invoice["amount"] == str(invoice.amount)
    assert json_invoice["currency"] == invoice.currency
    assert json_invoice["invoice_pdf_url"] is None


@pytest.mark.asyncio
async def test_update_billing_address(client: AsyncClient) -> None:
    payload = BillingAddressJson.from_model(billing_address).model_dump()
    response = await client.put("/api/workspaces/{workspace_id}/billing_address/", json=payload)
    assert response.status_code == 200
    json = response.json()
    assert json["name"] == billing_address.name
    assert json["company"] == billing_address.company
    assert json["address_line_1"] == billing_address.address_line_1
    assert json["address_line_2"] == billing_address.address_line_2
    assert json["postal_code"] == billing_address.postal_code
    assert json["city"] == billing_address.city
    assert json["state"] == billing_address.state
    assert json["country"] == billing_address.country


@pytest.mark.asyncio
async def test_get_billing_adderess(client: AsyncClient) -> None:
    response = await client.get("/api/workspaces/{workspace_id}/billing_address/")
    assert response.status_code == 200
    json = response.json()
    assert json["name"] == billing_address.name
    assert json["company"] == billing_address.company
    assert json["address_line_1"] == billing_address.address_line_1
    assert json["address_line_2"] == billing_address.address_line_2
    assert json["postal_code"] == billing_address.postal_code
    assert json["city"] == billing_address.city
    assert json["state"] == billing_address.state
    assert json["country"] == billing_address.country
