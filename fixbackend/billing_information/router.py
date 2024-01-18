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
from fixbackend.billing_information import schemas
from fixbackend.billing_information.models import PaymentMethod, PaymentMethods
from fixbackend.billing_information.schemas import (
    BillingEntryRead,
    ProductTier,
    WorkspaceBillingSettingsRead,
    WorkspaceBillingSettingsUpdate,
)
from fixbackend.billing_information.service import BillingEntryServiceDependency
from fixbackend.ids import SecurityTier, SubscriptionId
from fixbackend.subscription.subscription_repository import SubscriptionRepositoryDependency
from fixbackend.workspaces.dependencies import UserWorkspaceDependency
from typing import List

from fixbackend.errors import ResourceNotFound


def billing_info_router() -> APIRouter:
    router = APIRouter()

    @router.get("/{workspace_id}/billing_entries/")
    async def list_billing_enties(
        workspace: UserWorkspaceDependency, billing_info_service: BillingEntryServiceDependency
    ) -> List[BillingEntryRead]:
        """List all workspaces."""
        entries = await billing_info_service.list_billing_info(workspace.id)

        return [BillingEntryRead.from_model(entry) for entry in entries]

    @router.get("/{workspace_id}/billing")
    async def get_billing(
        user: AuthenticatedUser, workspace: UserWorkspaceDependency, billing_info_service: BillingEntryServiceDependency
    ) -> WorkspaceBillingSettingsRead:
        """Get a workspace billing."""
        payment_method = await billing_info_service.get_payment_methods(workspace, user.id)
        return WorkspaceBillingSettingsRead.from_model(workspace, payment_method)

    @router.put("/{workspace_id}/billing")
    async def update_billing(
        workspace: UserWorkspaceDependency,
        user: AuthenticatedUser,
        billing_info_service: BillingEntryServiceDependency,
        billing: WorkspaceBillingSettingsUpdate,
    ) -> WorkspaceBillingSettingsRead:
        """Update a workspace billing."""

        def tier(billing: WorkspaceBillingSettingsUpdate) -> SecurityTier:
            match billing.security_tier:
                case ProductTier.free:
                    return SecurityTier.Free
                case ProductTier.foundational:
                    return SecurityTier.Foundational
                case ProductTier.high_security:
                    return SecurityTier.HighSecurity

        def payment_method(method: schemas.PaymentMethod) -> PaymentMethod:
            match method:
                case schemas.NoPaymentMethod():
                    return PaymentMethods.NoPaymentMethod()
                case schemas.AwsSubscription():
                    return PaymentMethods.AwsSubscription(method.subscription_id)

        ws = await billing_info_service.update_billing(
            user, workspace, tier(billing), payment_method(billing.workspace_payment_method)
        )
        payment_methods = await billing_info_service.get_payment_methods(workspace, user.id)

        return WorkspaceBillingSettingsRead.from_model(ws, payment_methods)

    @router.put("/{workspace_id}/subscription/{subscription_id}")
    async def assign_subscription(
        workspace: UserWorkspaceDependency,
        user: AuthenticatedUser,
        subscription_repository: SubscriptionRepositoryDependency,
        subscription_id: SubscriptionId,
    ) -> None:
        """Assign a subscription to a workspace."""
        if not await subscription_repository.user_has_subscription(user.id, subscription_id):
            raise ResourceNotFound("Subscription not found")

        await subscription_repository.update_subscription_for_workspace(workspace.id, subscription_id)

    return router
