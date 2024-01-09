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


from typing import Annotated, List, Optional

from fastapi import Depends

from fixbackend.auth.models import User
from fixbackend.billing_information.models import (
    PaymentMethod,
    PaymentMethods,
    WorkspacePaymentMethods,
)

from fixbackend.ids import SecurityTier, UserId, WorkspaceId
from fixbackend.subscription.models import BillingEntry
from fixbackend.subscription.subscription_repository import SubscriptionRepository, SubscriptionRepositoryDependency
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository, WorkspaceRepositoryDependency
from fixbackend.errors import NotAllowed


class BillingEntryService:
    def __init__(
        self, subscription_repository: SubscriptionRepository, workspace_repository: WorkspaceRepository
    ) -> None:
        self.subscription_repository = subscription_repository
        self.workspace_repository = workspace_repository

    async def list_billing_info(self, workspace_id: WorkspaceId) -> List[BillingEntry]:
        billing_entries = [
            billing async for billing, _ in self.subscription_repository.list_billing_for_workspace(workspace_id)
        ]
        return billing_entries

    async def get_payment_methods(self, workspace: Workspace, user_id: UserId) -> WorkspacePaymentMethods:
        """List all awailable payment methods available for the workspace"""
        current: PaymentMethod = PaymentMethods.NoPaymentMethod()

        payment_methods: List[PaymentMethod] = []
        if workspace.security_tier == SecurityTier.Free:
            payment_methods.append(PaymentMethods.NoPaymentMethod())

        if current_subscription := await anext(
            self.subscription_repository.subscriptions(workspace_id=workspace.id, active=True), None
        ):
            current = PaymentMethods.AwsSubscription(subscription_id=current_subscription.id)
        for subscription in await self.subscription_repository.not_assigned_subscriptions(user_id=user_id):
            payment_methods.append(PaymentMethods.AwsSubscription(subscription_id=subscription.id))

        return WorkspacePaymentMethods(current=current, available=payment_methods)

    async def update_billing(
        self,
        user: User,
        workspace: Workspace,
        new_security_tier: Optional[SecurityTier] = None,
        new_payment_method: Optional[PaymentMethod] = None,
    ) -> Workspace:
        if new_security_tier is not None:
            if new_security_tier != SecurityTier.Free and new_payment_method is PaymentMethods.NoPaymentMethod():
                raise NotAllowed("Payment method is required for non-free tiers")

        current_tier = workspace.security_tier
        if current_tier != SecurityTier.Free and new_payment_method is not None:
            # at this point we could silently downgrade the security tier to free,
            # but explicit is better than implicit so the user must move to the free tier first
            if new_payment_method == PaymentMethods.NoPaymentMethod():
                raise NotAllowed("Cannot remove payment method for non-free tiers")

        if new_payment_method:
            match new_payment_method:
                case PaymentMethods.AwsSubscription(subscription_id):
                    await self.subscription_repository.update_subscription_for_workspace(
                        workspace_id=workspace.id, subscription_id=subscription_id
                    )
                case PaymentMethods.NoPaymentMethod():
                    await self.subscription_repository.update_subscription_for_workspace(
                        workspace_id=workspace.id, subscription_id=None
                    )

        if new_security_tier:
            return await self.workspace_repository.update_security_tier(
                user=user, workspace_id=workspace.id, security_tier=new_security_tier
            )

        return workspace


def get_billing_entry_service(
    subscription_repository: SubscriptionRepositoryDependency,
    workspace_repository: WorkspaceRepositoryDependency,
) -> BillingEntryService:
    return BillingEntryService(subscription_repository, workspace_repository)


BillingEntryServiceDependency = Annotated[BillingEntryService, Depends(get_billing_entry_service)]
