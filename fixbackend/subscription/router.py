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
from functools import partial
from typing import Callable

from fastapi import APIRouter, Form, Cookie, Response, Request
from starlette.responses import RedirectResponse

from fixbackend.auth.depedencies import OptionalAuthenticatedUser, AuthenticatedUser
from fixbackend.dependencies import FixDependencies, ServiceNames as SN
from fixbackend.subscription.aws_marketplace import AwsMarketplaceHandler

AddUrlName = "aws-marketplace-subscription-add"


def subscription_router(deps: FixDependencies) -> APIRouter:
    router = APIRouter()
    market_place_handler: Callable[[], AwsMarketplaceHandler] = partial(  # type: ignore
        deps.service, SN.aws_marketplace_handler, AwsMarketplaceHandler
    )

    # Attention: Changing this route will break the AWS Marketplace integration!
    @router.post("/cloud/callbacks/aws/marketplace")
    async def aws_marketplace_fulfillment(
        request: Request,
        maybe_user: OptionalAuthenticatedUser,
        x_amzn_marketplace_token: str = Form(alias="x-amzn-marketplace-token"),
    ) -> Response:
        if user := maybe_user:
            # add marketplace subscription
            await market_place_handler().subscribed(user, x_amzn_marketplace_token)
            # load the app and show a message
            return RedirectResponse("/?message=aws-marketplace-subscribed")
        else:
            add_url = request.scope["router"].url_path_for(AddUrlName)
            response = RedirectResponse(f"/auth/login?returnUrl={add_url}")
            response.set_cookie("fix-aws-marketplace-token", x_amzn_marketplace_token, secure=True, httponly=True)
            return response

    @router.get("/subscriptions/aws/marketplace/add", response_model=None, name=AddUrlName)
    async def aws_marketplace_fulfillment_after_login(
        user: AuthenticatedUser, fix_aws_marketplace_token: str = Cookie(None, alias="fix-aws-marketplace-token")
    ) -> Response:
        if fix_aws_marketplace_token is not None:
            await market_place_handler().subscribed(user, fix_aws_marketplace_token)
            # load the app and show a message
            response = RedirectResponse("/?message=aws-marketplace-subscribed")
            response.set_cookie("fix-aws-marketplace-token", "", expires=0)  # delete the cookie
            return response
        else:
            raise ValueError("No AWS token found!")

    return router
