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

from fastapi import APIRouter

from fixbackend.cloud_accounts.schemas import AwsCloudFormationLambdaCallbackParameters, LastScanInfo, ScannedAccount
from fixbackend.cloud_accounts.dependencies import CloudAccountServiceDependency
from fixbackend.ids import FixCloudAccountId
from fixbackend.workspaces.dependencies import UserWorkspaceDependency

log = logging.getLogger(__name__)


def cloud_accounts_router() -> APIRouter:
    router = APIRouter()

    @router.delete("/{workspace_id}/cloud_account/{cloud_account_id}")
    async def delete_cloud_account(
        workspace: UserWorkspaceDependency,
        cloud_account_id: FixCloudAccountId,
        service: CloudAccountServiceDependency,
    ) -> None:
        await service.delete_cloud_account(cloud_account_id, workspace.id)

    @router.get("/{workspace_id}/cloud_accounts/last_scan")
    async def last_scan(
        workspace: UserWorkspaceDependency,
        service: CloudAccountServiceDependency,
    ) -> LastScanInfo:
        last_scan = await service.last_scan(workspace.id)
        if last_scan is None:
            return LastScanInfo(
                workspace_id=workspace.id,
                accounts=[],
                next_scan=None,
            )
        return LastScanInfo(
            workspace_id=workspace.id,
            accounts=[
                ScannedAccount(
                    account_id=account.account_id,
                    resource_scanned=account.resources_scanned,
                    duration=account.duration_seconds,
                )
                for account in last_scan.accounts.values()
            ],
            next_scan=last_scan.next_scan,
        )

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
