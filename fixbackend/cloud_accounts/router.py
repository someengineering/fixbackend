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

from fastapi import APIRouter, HTTPException

from fixbackend.cloud_accounts.schemas import AwsCloudFormationLambdaCallbackParameters
from fixbackend.cloud_accounts.service import CloudAccountServiceDependency
from fixbackend.ids import CloudAccountId
from fixbackend.auth.current_user_dependencies import UserWorkspacesDependency
from fixbackend.ids import WorkspaceId

log = logging.getLogger(__name__)


def cloud_accounts_router() -> APIRouter:
    router = APIRouter()

    @router.delete("/{workspace_id}/cloud_account/{cloud_account_id}")
    async def delete_cloud_account(
        workspace_id: WorkspaceId,
        cloud_account_id: CloudAccountId,
        user_tenants: UserWorkspacesDependency,
        service: CloudAccountServiceDependency,
    ) -> None:
        if workspace_id not in user_tenants:
            raise HTTPException(status_code=403, detail="User does not have access to this organization")

        await service.delete_cloud_account(cloud_account_id, workspace_id)

    return router


def cloud_accounts_callback_router() -> APIRouter:
    router = APIRouter()

    @router.post("/callbacks/aws/cf")
    async def aws_cloudformation_callback(
        payload: AwsCloudFormationLambdaCallbackParameters, service: CloudAccountServiceDependency
    ) -> None:
        await service.create_aws_account(
            payload.workspace_id, payload.account_id, payload.role_name, payload.external_id
        )
        return None

    return router
