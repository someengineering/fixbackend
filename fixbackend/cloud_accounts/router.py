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
import logging

from fixbackend.cloud_accounts.schemas import AwsCloudFormationLambdaCallbackParameters


log = logging.getLogger(__name__)


def cloud_accounts_router() -> APIRouter:
    router = APIRouter()

    @router.post("/callbacks/aws/cf")
    def aws_cloudformation_callback(payload: AwsCloudFormationLambdaCallbackParameters) -> None:
        log.info((f"AWS cloudformation callback: {payload}"))

    return router
