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

from datetime import timedelta
import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from fixcloudutils.util import utc

from fixbackend.auth.depedencies import AuthenticatedUser
from fixbackend.permissions.models import WorkspacePermissions
from fixbackend.permissions.permission_checker import WorkspacePermissionChecker
from fixbackend.cloud_accounts.dependencies import CloudAccountServiceDependency
from fixbackend.cloud_accounts.models import CloudAccountStates
from fixbackend.cloud_accounts.schemas import (
    AwsCloudAccountUpdate,
    AwsCloudFormationLambdaCallbackParameters,
    CloudAccountList,
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
    ) -> CloudAccountList:
        cloud_accounts = await service.list_accounts(workspace.id)
        sorted_by_created_at = sorted(cloud_accounts, key=lambda ca: ca.created_at, reverse=True)
        now = utc()
        last24hours = now - timedelta(days=1)
        recent = []
        added = []
        detected = []

        for cloud_account in sorted_by_created_at:
            match cloud_account.state:
                case CloudAccountStates.Detected():
                    detected.append(CloudAccountRead.from_model(cloud_account))
                case _:
                    if cloud_account.created_at > last24hours:
                        recent.append(CloudAccountRead.from_model(cloud_account))
                    else:
                        added.append(CloudAccountRead.from_model(cloud_account))

        return CloudAccountList(recent=recent, added=added, discovered=detected)

    @router.patch("/{workspace_id}/cloud_account/{cloud_account_id}")
    async def update_cloud_account(
        workspace: UserWorkspaceDependency,
        cloud_account_id: FixCloudAccountId,
        service: CloudAccountServiceDependency,
        update: AwsCloudAccountUpdate,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update_cloud_accounts))],
    ) -> CloudAccountRead:
        updated = await service.update_cloud_account_name(workspace.id, cloud_account_id, update.name)
        return CloudAccountRead.from_model(updated)

    @router.delete("/{workspace_id}/cloud_account/{cloud_account_id}")
    async def delete_cloud_account(
        user: AuthenticatedUser,
        workspace: UserWorkspaceDependency,
        cloud_account_id: FixCloudAccountId,
        service: CloudAccountServiceDependency,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update_cloud_accounts))],
    ) -> None:
        await service.delete_cloud_account(user.id, cloud_account_id, workspace.id)

    @router.patch("/{workspace_id}/cloud_account/{cloud_account_id}/enable")
    async def enable_cloud_account(
        workspace: UserWorkspaceDependency,
        cloud_account_id: FixCloudAccountId,
        service: CloudAccountServiceDependency,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update_cloud_accounts))],
    ) -> CloudAccountRead:
        updated = await service.update_cloud_account_enabled(workspace.id, cloud_account_id, enabled=True)
        return CloudAccountRead.from_model(updated)

    @router.patch("/{workspace_id}/cloud_account/{cloud_account_id}/disable")
    async def disable_cloud_account(
        workspace: UserWorkspaceDependency,
        cloud_account_id: FixCloudAccountId,
        service: CloudAccountServiceDependency,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update_cloud_accounts))],
    ) -> CloudAccountRead:
        updated = await service.update_cloud_account_enabled(workspace.id, cloud_account_id, enabled=False)
        return CloudAccountRead.from_model(updated)

    @router.patch("/{workspace_id}/cloud_account/{cloud_account_id}/scan/enable")
    async def enable_cloud_account_scan(
        workspace: UserWorkspaceDependency,
        cloud_account_id: FixCloudAccountId,
        service: CloudAccountServiceDependency,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update_cloud_accounts))],
    ) -> CloudAccountRead:
        updated = await service.update_cloud_account_scan_enabled(workspace.id, cloud_account_id, scan=True)
        return CloudAccountRead.from_model(updated)

    @router.patch("/{workspace_id}/cloud_account/{cloud_account_id}/scan/disable")
    async def disable_cloud_account_scan(
        workspace: UserWorkspaceDependency,
        cloud_account_id: FixCloudAccountId,
        service: CloudAccountServiceDependency,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update_cloud_accounts))],
    ) -> CloudAccountRead:
        updated = await service.update_cloud_account_scan_enabled(workspace.id, cloud_account_id, scan=False)
        return CloudAccountRead.from_model(updated)

    @router.get("/{workspace_id}/cloud_accounts/last_scan")
    async def last_scan(
        workspace: UserWorkspaceDependency,
        service: CloudAccountServiceDependency,
    ) -> LastScanInfo:
        accounts = await service.list_accounts(workspace.id)
        if not accounts:
            return LastScanInfo.empty(workspace.id)
        return LastScanInfo(
            workspace_id=workspace.id,
            accounts=[
                ScannedAccount(
                    account_id=account.account_id,
                    resource_scanned=account.last_scan_resources_scanned,
                    duration=account.last_scan_duration_seconds,
                    started_at=account.last_scan_started_at,
                )
                for account in accounts
                if account.last_scan_started_at
            ],
            next_scan=accounts[0].next_scan,
        )

    return router


def cloud_accounts_callback_router() -> APIRouter:
    router = APIRouter()

    @router.post("/callbacks/aws/cf")
    async def aws_cloudformation_callback(
        payload: AwsCloudFormationLambdaCallbackParameters, service: CloudAccountServiceDependency
    ) -> None:
        set_workspace_id(payload.workspace_id)
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
