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
from typing import List

from fastapi import APIRouter

from fixbackend.cloud_accounts.dependencies import CloudAccountServiceDependency
from fixbackend.cloud_accounts.schemas import (
    AwsCloudAccountUpdate,
    AwsCloudFormationLambdaCallbackParameters,
    CloudAccountRead,
    LastScanInfo,
    ScannedAccount,
)
from fixbackend.ids import FixCloudAccountId
from fixbackend.logging_context import set_cloud_account_id, set_workspace_id
from fixbackend.workspaces.dependencies import UserWorkspaceDependency

log = logging.getLogger(__name__)


def cloud_accounts_router() -> APIRouter:
    router = APIRouter()

    @router.get("/{workspace_id}/cloud_account/{cloud_account_id}")
    async def get_cloud_account(
        workspace: UserWorkspaceDependency,
        cloud_account_id: FixCloudAccountId,
        service: CloudAccountServiceDependency,
    ) -> CloudAccountRead:
        cloud_account = await service.get_cloud_account(cloud_account_id, workspace.id)
        return CloudAccountRead.from_model(cloud_account)

    @router.get("/{workspace_id}/cloud_accounts")
    async def list_cloud_accounts(
        workspace: UserWorkspaceDependency, service: CloudAccountServiceDependency
    ) -> List[CloudAccountRead]:
        cloud_accounts = await service.list_accounts(workspace.id)
        last_scan = await service.last_scan(workspace.id)
        accounts = last_scan.accounts if last_scan else {}
        next_scan = last_scan.next_scan if last_scan else None
        return [
            CloudAccountRead.from_model(cloud_account, accounts.get(cloud_account.id), next_scan)
            for cloud_account in cloud_accounts
        ]

    @router.patch("/{workspace_id}/cloud_account/{cloud_account_id}")
    async def update_cloud_account(
        workspace: UserWorkspaceDependency,
        cloud_account_id: FixCloudAccountId,
        service: CloudAccountServiceDependency,
        update: AwsCloudAccountUpdate,
    ) -> CloudAccountRead:
        updated = await service.update_cloud_account_name(workspace.id, cloud_account_id, update.name)
        return CloudAccountRead.from_model(updated)

    @router.delete("/{workspace_id}/cloud_account/{cloud_account_id}")
    async def delete_cloud_account(
        workspace: UserWorkspaceDependency,
        cloud_account_id: FixCloudAccountId,
        service: CloudAccountServiceDependency,
    ) -> None:
        await service.delete_cloud_account(cloud_account_id, workspace.id)

    @router.patch("/{workspace_id}/cloud_account/{cloud_account_id}/enable")
    async def enable_cloud_account(
        workspace: UserWorkspaceDependency,
        cloud_account_id: FixCloudAccountId,
        service: CloudAccountServiceDependency,
    ) -> CloudAccountRead:
        updated = await service.enable_cloud_account(workspace.id, cloud_account_id)
        return CloudAccountRead.from_model(updated)

    @router.patch("/{workspace_id}/cloud_account/{cloud_account_id}/disable")
    async def disable_cloud_account(
        workspace: UserWorkspaceDependency,
        cloud_account_id: FixCloudAccountId,
        service: CloudAccountServiceDependency,
    ) -> CloudAccountRead:
        updated = await service.disable_cloud_account(workspace.id, cloud_account_id)
        return CloudAccountRead.from_model(updated)

    @router.get("/{workspace_id}/cloud_accounts/last_scan")
    async def last_scan(
        workspace: UserWorkspaceDependency,
        service: CloudAccountServiceDependency,
    ) -> LastScanInfo:
        last_scan = await service.last_scan(workspace.id)
        if last_scan is None:
            return LastScanInfo.empty(workspace.id)
        return LastScanInfo(
            workspace_id=workspace.id,
            accounts=[
                ScannedAccount(
                    account_id=account.account_id,
                    resource_scanned=account.resources_scanned,
                    duration=account.duration_seconds,
                    started_at=account.started_at,
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
        set_workspace_id(str(payload.workspace_id))
        set_cloud_account_id(payload.account_id)
        await service.create_aws_account(
            workspace_id=payload.workspace_id,
            account_id=payload.account_id,
            role_name=payload.role_name,
            external_id=payload.external_id,
            account_name=None,
        )
        return None

    return router
