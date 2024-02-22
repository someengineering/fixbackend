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
from fixbackend.dependencies import FixDependency, ServiceNames
from fixbackend.domain_events.events import ProductTierChanged
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.errors import NotAllowed
from fixbackend.ids import ProductTier, UserId, WorkspaceId
from fixbackend.subscription.models import BillingEntry
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository


class BillingEntryService:
    def __init__(
        self,
        subscription_repository: SubscriptionRepository,
        workspace_repository: WorkspaceRepository,
        domain_event_sender: DomainEventPublisher,
    ) -> None:
        self.subscription_repository = subscription_repository
        self.workspace_repository = workspace_repository
        self.domain_event_sender = domain_event_sender

    async def list_billing_info(self, workspace_id: WorkspaceId) -> List[BillingEntry]:
        billing_entries = [
            billing async for billing, _ in self.subscription_repository.list_billing_for_workspace(workspace_id)
        ]
        return billing_entries

    async def get_payment_methods(self, workspace: Workspace, user_id: UserId) -> WorkspacePaymentMethods:
        """List all awailable payment methods available for the workspace"""
        current: PaymentMethod = PaymentMethods.NoPaymentMethod()

        payment_methods: List[PaymentMethod] = []
        if workspace.product_tier == ProductTier.Free:
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
        new_product_tier: Optional[ProductTier] = None,
        new_payment_method: Optional[PaymentMethod] = None,
    ) -> Workspace:
        if new_product_tier is not None:
            if new_product_tier != ProductTier.Free and new_payment_method is PaymentMethods.NoPaymentMethod():
                raise NotAllowed("Payment method is required for non-free tiers")

        current_tier = workspace.product_tier
        if current_tier != ProductTier.Free and new_payment_method is not None:
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

        if new_product_tier:
            workspace = await self.workspace_repository.update_security_tier(
                user=user, workspace_id=workspace.id, security_tier=new_product_tier
            )
            event = ProductTierChanged(
                workspace.id,
                user.id,
                new_product_tier,
                new_product_tier.paid,
                new_product_tier > current_tier,
                current_tier,
            )
            await self.domain_event_sender.publish(event)

        return workspace


def get_billing_entry_service(fix_dependency: FixDependency) -> BillingEntryService:
    return fix_dependency.service(ServiceNames.billing_entry_service, BillingEntryService)


BillingEntryServiceDependency = Annotated[BillingEntryService, Depends(get_billing_entry_service)]
