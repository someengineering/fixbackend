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


from typing import List, Optional

from fastapi import APIRouter, Depends, Response, status

from fixbackend.auth.depedencies import AuthenticatedUser
from fixbackend.config import Config
from fixbackend.permissions.models import WorkspacePermissions
from fixbackend.permissions.permission_checker import WorkspacePermissionChecker
from fixbackend.billing import schemas
from fixbackend.billing.models import PaymentMethod, PaymentMethods
from fixbackend.billing.schemas import (
    BillingEntryRead,
    WorkspaceBillingSettingsRead,
    WorkspaceBillingSettingsUpdate,
)
from fixbackend.billing.service import BillingEntryServiceDependency
from fixbackend.errors import ResourceNotFound
from fixbackend.ids import ProductTier, SubscriptionId, WorkspaceId
from fixbackend.subscription.subscription_repository import SubscriptionRepositoryDependency
from fixbackend.workspaces.dependencies import UserWorkspaceDependency
from fixbackend.workspaces.repository import WorkspaceRepositoryDependency


def billing_info_router(config: Config) -> APIRouter:
    router = APIRouter()

    @router.get("/{workspace_id}/billing_entries/")
    async def list_billing_entries(
        workspace: UserWorkspaceDependency,
        billing_info_service: BillingEntryServiceDependency,
        _: bool = Depends(WorkspacePermissionChecker(WorkspacePermissions.read_billing)),
    ) -> List[BillingEntryRead]:
        entries = await billing_info_service.list_billing_info(workspace.id)
        return [BillingEntryRead.from_model(entry) for entry in entries]

    @router.get("/{workspace_id}/billing")
    async def get_billing(
        user: AuthenticatedUser,
        workspace: UserWorkspaceDependency,
        billing_info_service: BillingEntryServiceDependency,
        _: bool = Depends(WorkspacePermissionChecker(WorkspacePermissions.read_billing)),
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
        _: bool = Depends(WorkspacePermissionChecker(WorkspacePermissions.update_billing)),
    ) -> WorkspaceBillingSettingsRead:
        """Update a workspace billing."""

        def payment_method(billing: WorkspaceBillingSettingsUpdate) -> Optional[PaymentMethod]:
            match billing.workspace_payment_method:
                case schemas.NoPaymentMethod():
                    return PaymentMethods.NoPaymentMethod()
                case schemas.StripeSubscription():
                    return PaymentMethods.StripeSubscription(billing.workspace_payment_method.subscription_id)
                case schemas.AwsSubscription():
                    return PaymentMethods.AwsSubscription(billing.workspace_payment_method.subscription_id)
                case None:
                    return None

        def product_tier(billing: WorkspaceBillingSettingsUpdate) -> Optional[ProductTier]:
            if billing.product_tier is None:
                return None
            return billing.product_tier.to_tier()

        ws = await billing_info_service.update_billing(
            user.id, workspace, product_tier(billing), payment_method(billing)
        )
        payment_methods = await billing_info_service.get_payment_methods(workspace, user.id)

        return WorkspaceBillingSettingsRead.from_model(ws, payment_methods)

    @router.put("/{workspace_id}/subscription/{subscription_id}")
    async def assign_subscription(
        workspace: UserWorkspaceDependency,
        user: AuthenticatedUser,
        subscription_repository: SubscriptionRepositoryDependency,
        workspace_repository: WorkspaceRepositoryDependency,
        subscription_id: SubscriptionId,
        _: bool = Depends(WorkspacePermissionChecker(WorkspacePermissions.update_billing)),
    ) -> None:
        """Assign a subscription to a workspace."""
        if not await subscription_repository.user_has_subscription(user.id, subscription_id):
            raise ResourceNotFound("Subscription not found")

        await workspace_repository.update_subscription(workspace.id, subscription_id)

    @router.get("/{workspace_id}/aws_marketplace_product")
    async def redirect_to_aws_marketplace_product(
        workspace_id: WorkspaceId,
    ) -> Response:
        response = Response(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": config.aws_marketplace_url},
        )
        return response

    return router
