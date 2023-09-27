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

import logging
import uuid

from fastapi import APIRouter

from fixbackend.cloud_accounts.models import AwsCloudAccount
from fixbackend.cloud_accounts.schemas import AwsCloudFormationLambdaCallbackParameters
from fixbackend.cloud_accounts.service import CloudAccountServiceDependency
from fixbackend.ids import CloudAccountId

log = logging.getLogger(__name__)


def cloud_accounts_router() -> APIRouter:
    router = APIRouter()

    @router.post("/callbacks/aws/cf")
    async def aws_cloudformation_callback(
        payload: AwsCloudFormationLambdaCallbackParameters, service: CloudAccountServiceDependency
    ) -> None:
        cloud_account = AwsCloudAccount(
            id=CloudAccountId(uuid.uuid4()),
            tenant_id=payload.tenant_id,
            account_id=payload.account_id,
            role_name=payload.role_name,
        )
        await service.create_account(cloud_account, payload.external_id)

    return router
