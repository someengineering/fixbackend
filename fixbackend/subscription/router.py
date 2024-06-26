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
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
import logging
from typing import Optional

from fastapi import APIRouter, Form, Cookie, Response, Request, Depends, status
from starlette.responses import RedirectResponse, JSONResponse

from fixbackend.auth.depedencies import OptionalAuthenticatedUser, AuthenticatedUser
from fixbackend.billing.schemas import ProductTierRead
from fixbackend.dependencies import FixDependencies, ServiceNames
from fixbackend.ids import WorkspaceId
from fixbackend.permissions.models import workspace_billing_admin_permissions
from fixbackend.permissions.permission_checker import WorkspacePermissionChecker
from fixbackend.subscription.aws_marketplace import AwsMarketplaceHandlerDependency
from fixbackend.subscription.stripe_subscription import StripeServiceDependency
from fixbackend.subscription.subscription_repository import AwsTierPreferenceRepository
from fixbackend.workspaces.dependencies import UserWorkspaceDependency

AddUrlName = "aws-marketplace-subscription-add"
BackFromStripe = "back-from-stripe"
MarketplaceTokenCookie = "fix-aws-marketplace-token"
log = logging.getLogger(__name__)


def subscription_router(fix: FixDependencies) -> APIRouter:
    router = APIRouter()

    config = fix.config
    aws_tier_preference_repo = fix.service(ServiceNames.aws_tier_preference_repo, AwsTierPreferenceRepository)

    # Attention: Changing this route will break the AWS Marketplace integration!
    @router.post("/cloud/callbacks/aws/marketplace", include_in_schema=False)
    async def aws_marketplace_fulfillment(
        request: Request,
        x_amzn_marketplace_token: str = Form(alias="x-amzn-marketplace-token"),
    ) -> Response:
        # Cross-Origin Post Request: we will not receive our auth cookie here.
        # Store the token in a cookie and redirect to the marketplace add page.
        # Use a 303 status code here to force a GET request instead of a POST request.
        response = RedirectResponse(request.scope["router"].url_path_for(AddUrlName), status_code=303)
        response.set_cookie(MarketplaceTokenCookie, x_amzn_marketplace_token, secure=True, httponly=True)
        return response

    @router.get("/subscriptions/aws/marketplace/add", response_model=None, name=AddUrlName, include_in_schema=False)
    async def aws_marketplace_fulfillment_after_login(
        request: Request,
        maybe_user: OptionalAuthenticatedUser,
        marketplace_handler: AwsMarketplaceHandlerDependency,
        fix_aws_marketplace_token: str = Cookie(None, alias="fix-aws-marketplace-token"),
    ) -> Response:
        if maybe_user is None:  # not logged in
            add_url = request.scope["router"].url_path_for(AddUrlName)
            return RedirectResponse(f"/auth/login?returnUrl={add_url}")
        elif (user := maybe_user) and fix_aws_marketplace_token is not None:  # logged in and token present
            subscription, workspace_assigned = await marketplace_handler.subscribed(user, fix_aws_marketplace_token)
            if not workspace_assigned:
                response = RedirectResponse(
                    f"{config.service_base_url}/subscription/choose-workspace?subscription_id={subscription.id}"
                )
                return response
            # load the app and show a message
            response = RedirectResponse(
                f"{config.service_base_url}/workspace-settings/billing-receipts?message=aws-marketplace-subscribed"
            )
            response.set_cookie(MarketplaceTokenCookie, expires=0, secure=True, httponly=True)  # delete the cookie
            return response
        else:  # something went wrong
            raise ValueError("No AWS token found!")

    @router.get("/workspaces/{workspace_id}/aws_marketplace_product")
    async def redirect_to_aws_marketplace_product(
        workspace_id: WorkspaceId, product_tier: Optional[ProductTierRead] = None
    ) -> Response:

        if product_tier:
            await aws_tier_preference_repo.create(workspace_id, product_tier.to_tier())

        response = Response(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": config.aws_marketplace_url},
        )
        return response

    @router.get("/workspaces/{workspace_id}/subscriptions/stripe", include_in_schema=False)
    async def redirect_to_stripe(
        workspace: UserWorkspaceDependency,
        stripe_service: StripeServiceDependency,
        request: Request,
        product_tier: Optional[ProductTierRead] = None,
        _: bool = Depends(WorkspacePermissionChecker(workspace_billing_admin_permissions)),
    ) -> Response:
        return_url = request.url_for(BackFromStripe, workspace_id=workspace.id)

        desired_product_tier = product_tier.to_tier() if product_tier is not None else None

        url = await stripe_service.redirect_to_stripe(workspace, str(return_url), desired_product_tier)
        return RedirectResponse(url)

    @router.get("/workspaces/{workspace_id}/subscriptions/stripe/back", include_in_schema=False, name=BackFromStripe)
    async def back_from_stripe(_: AuthenticatedUser, success: Optional[bool] = None) -> Response:
        # success is only returned from the checkout, not the customer portal (hence optional)
        # in case the user did the checkout successfully, we want to show a message
        # otherwise nothing is shown - the user can visit the checkout as often as they want
        if success:
            return RedirectResponse("/workspace-settings/billing-receipts?message=stripe-subscribed")
        return RedirectResponse("/workspace-settings/billing-receipts")

    @router.post("/subscriptions/stripe/events", include_in_schema=False)
    async def stripe_callback(request: Request, stripe_service: StripeServiceDependency) -> Response:
        signature = request.headers.get("Stripe-Signature")
        assert signature is not None, "No Stripe-Signature header found"
        js_bytes = await request.body()
        try:
            await stripe_service.handle_event(js_bytes.decode("utf-8"), signature)
            return JSONResponse({"success": True})
        except Exception as e:
            log.error("Could not handle stripe event", exc_info=True)
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    return router
