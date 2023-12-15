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


from fastapi import APIRouter
from fixbackend.auth.depedencies import AuthenticatedUser
from fixbackend.invoices.billing_address_repository import BillingAddressRepositoryDependency
from fixbackend.invoices.models import BillingAdderss
from fixbackend.invoices.schemas import BillingAddressJson, InvoiceRead
from fixbackend.invoices.service import InvoiceServiceDependency
from fixbackend.workspaces.dependencies import UserWorkspaceDependency
from typing import List
from fixbackend.errors import ResourceNotFound


def invoices_router() -> APIRouter:
    router = APIRouter()

    @router.get("/{workspace_id}/invoices/")
    async def list_invoices(
        workspace: UserWorkspaceDependency, invoice_service: InvoiceServiceDependency
    ) -> List[InvoiceRead]:
        """List all workspaces."""
        invoices = await invoice_service.list_invoices(workspace.id)

        return [InvoiceRead.from_model(invoice) for invoice in invoices]

    @router.get("/{workspace_id}/billing_address/")
    async def get_billing_address(
        workspace: UserWorkspaceDependency,
        user: AuthenticatedUser,
        billing_address_repository: BillingAddressRepositoryDependency,
    ) -> BillingAddressJson:
        """List all workspaces."""

        address = await billing_address_repository.get_billing_address(user.id)
        if address is None:
            raise ResourceNotFound("Billing address not found")

        return BillingAddressJson.from_model(address)

    @router.put("/{workspace_id}/billing_address/")
    async def update_billing_address(
        workspace: UserWorkspaceDependency,
        user: AuthenticatedUser,
        billing_address_repository: BillingAddressRepositoryDependency,
        address: BillingAddressJson,
    ) -> BillingAddressJson:
        """List all workspaces."""

        new_address = BillingAdderss(
            user_id=user.id,
            name=address.name,
            company=address.company,
            address_line_1=address.address_line_1,
            address_line_2=address.address_line_2,
            postal_code=address.postal_code,
            city=address.city,
            state=address.state,
            country=address.country,
        )

        existing = await billing_address_repository.get_billing_address(user.id)
        if existing is None:
            update = await billing_address_repository.create_billing_address(user.id, new_address)
        else:
            update = await billing_address_repository.update_billing_address(user.id, new_address)

        return BillingAddressJson.from_model(update)

    return router
