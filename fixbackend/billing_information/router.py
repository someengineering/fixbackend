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
from fixbackend.billing_information.schemas import BillingEntryRead
from fixbackend.billing_information.service import BillingEntryServiceDependency
from fixbackend.workspaces.dependencies import UserWorkspaceDependency
from typing import List


def billing_info_router() -> APIRouter:
    router = APIRouter()

    @router.get("/{workspace_id}/billing_entries/")
    async def list_billing_enties(
        workspace: UserWorkspaceDependency, invoice_service: BillingEntryServiceDependency
    ) -> List[BillingEntryRead]:
        """List all workspaces."""
        invoices = await invoice_service.list_billing_info(workspace.id)

        return [BillingEntryRead.from_model(invoice) for invoice in invoices]

    return router
