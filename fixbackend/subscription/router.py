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

from fastapi import APIRouter, Form, Cookie, Response, Request
from starlette.responses import RedirectResponse

from fixbackend.auth.depedencies import OptionalAuthenticatedUser
from fixbackend.subscription.aws_marketplace import AwsMarketplaceHandlerDependency

AddUrlName = "aws-marketplace-subscription-add"
MarketplaceTokenCookie = "fix-aws-marketplace-token"


def subscription_router() -> APIRouter:
    router = APIRouter()

    # Attention: Changing this route will break the AWS Marketplace integration!
    @router.post("/cloud/callbacks/aws/marketplace")
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

    @router.get("/subscriptions/aws/marketplace/add", response_model=None, name=AddUrlName)
    async def aws_marketplace_fulfillment_after_login(
        request: Request,
        maybe_user: OptionalAuthenticatedUser,
        market_place_handler: AwsMarketplaceHandlerDependency,
        fix_aws_marketplace_token: str = Cookie(None, alias="fix-aws-marketplace-token"),
    ) -> Response:
        if maybe_user is None:  # not logged in
            add_url = request.scope["router"].url_path_for(AddUrlName)
            return RedirectResponse(f"/auth/login?returnUrl={add_url}")
        elif (user := maybe_user) and fix_aws_marketplace_token is not None:  # logged in and token present
            subscription = await market_place_handler.subscribed(user, fix_aws_marketplace_token)
            if subscription.workspace_id is None:  # no workspace yet
                response = RedirectResponse(f"/assigh-subscription?id={subscription.id}")
                return response
            # load the app and show a message
            response = RedirectResponse("/?message=aws-marketplace-subscribed")
            response.set_cookie(MarketplaceTokenCookie, expires=0, secure=True, httponly=True)  # delete the cookie
            return response
        else:  # something went wrong
            raise ValueError("No AWS token found!")

    return router
