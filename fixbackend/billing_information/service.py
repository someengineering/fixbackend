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


from typing import Annotated, List

from fastapi import Depends

from fixbackend.ids import WorkspaceId
from fixbackend.subscription.models import BillingEntry
from fixbackend.subscription.subscription_repository import SubscriptionRepository, SubscriptionRepositoryDependency


class BillingEntryService:
    def __init__(self, subscription_repository: SubscriptionRepository) -> None:
        self.subscription_repository = subscription_repository

    async def list_billing_info(self, workspace_id: WorkspaceId) -> List[BillingEntry]:
        billing_entries = [
            billing async for billing, _ in self.subscription_repository.list_billing_for_workspace(workspace_id)
        ]
        return billing_entries


def get_billing_entry_service(
    subscription_repository: SubscriptionRepositoryDependency,
) -> BillingEntryService:
    return BillingEntryService(subscription_repository)


BillingEntryServiceDependency = Annotated[BillingEntryService, Depends(get_billing_entry_service)]
