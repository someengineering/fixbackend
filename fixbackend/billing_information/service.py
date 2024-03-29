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
from fixbackend.subscription.models import AwsMarketplaceSubscription, BillingEntry
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

        async def get_current_subscription() -> Optional[AwsMarketplaceSubscription]:
            if workspace.subscription_id is None:
                return None

            if not (subscription := await self.subscription_repository.get_subscription(workspace.subscription_id)):
                return None

            if not subscription.active:
                return None

            return subscription

        if current_subscription := await get_current_subscription():
            current = PaymentMethods.AwsSubscription(subscription_id=current_subscription.id)

        async for subscription in self.subscription_repository.subscriptions(user_id=user_id, active=True):

            payment_methods.append(PaymentMethods.AwsSubscription(subscription_id=subscription.id))

        return WorkspacePaymentMethods(current=current, available=payment_methods)

    async def update_billing(
        self,
        user: User,
        workspace: Workspace,
        new_product_tier: Optional[ProductTier] = None,
        new_payment_method: Optional[PaymentMethod] = None,
    ) -> Workspace:
        current_tier = workspace.product_tier
        workspace_payment_methods = await self.get_payment_methods(workspace, user.id)

        def payment_method_available() -> bool:
            new_payment_method_provided = (
                new_payment_method is not None and new_payment_method is not PaymentMethods.NoPaymentMethod()
            )
            has_existing_payment_method = workspace_payment_methods.current is not PaymentMethods.NoPaymentMethod()
            return new_payment_method_provided or has_existing_payment_method

        # validate the product tier update
        if new_product_tier is not None:
            # non-free tiers require a valid payment method
            if new_product_tier.paid and not payment_method_available():
                raise NotAllowed("You must have a payment method to use non-free tiers")

        # validate the payment method update
        if new_payment_method is not None:
            # the payment method must be assigned to the workspace
            if new_payment_method not in workspace_payment_methods.available:
                raise NotAllowed("The payment method is not available for this workspace")

            # removing the payment method is not allowed for non-free tiers
            if new_payment_method is PaymentMethods.NoPaymentMethod() and current_tier.paid:
                raise NotAllowed("Cannot remove payment method for non-free tiers, downgrade the tier first")

        async def update_payment_method(payment_method: PaymentMethod) -> Workspace:
            if payment_method == workspace_payment_methods.current:
                return workspace
            match payment_method:
                case PaymentMethods.AwsSubscription(subscription_id):
                    return await self.workspace_repository.update_subscription(workspace.id, subscription_id)
                case PaymentMethods.NoPaymentMethod():
                    return await self.workspace_repository.update_subscription(workspace.id, None)

        async def update_product_tier(product_tier: ProductTier) -> Workspace:
            if product_tier == current_tier:
                return workspace

            updated_workspace = await self.workspace_repository.update_product_tier(
                workspace_id=workspace.id, tier=product_tier
            )
            event = ProductTierChanged(
                workspace.id,
                user.id,
                product_tier,
                product_tier.paid,
                product_tier > current_tier,
                current_tier,
            )
            await self.domain_event_sender.publish(event)
            return updated_workspace

        # update the payment method
        if new_payment_method:
            workspace = await update_payment_method(new_payment_method)

        # update the product tier
        if new_product_tier:
            workspace = await update_product_tier(new_product_tier)

        return workspace


def get_billing_entry_service(fix_dependency: FixDependency) -> BillingEntryService:
    return fix_dependency.service(ServiceNames.billing_entry_service, BillingEntryService)


BillingEntryServiceDependency = Annotated[BillingEntryService, Depends(get_billing_entry_service)]
