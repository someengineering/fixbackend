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

import json
import logging
from datetime import timedelta
from enum import StrEnum
from typing import Annotated, AsyncIterator, Optional
from uuid import UUID

from azure.identity.aio import AuthorizationCodeCredential
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from fixcloudutils.util import utc
from google.auth.exceptions import MalformedError
from googleapiclient.errors import HttpError
from msal import ConfidentialClientApplication

from fixbackend.auth.depedencies import AuthenticatedUser
from fixbackend.cloud_accounts.azure_subscription_repo import AzureSubscriptionCredentialsRepository
from fixbackend.cloud_accounts.azure_subscription_service import AzureSubscriptionService
from fixbackend.cloud_accounts.dependencies import CloudAccountServiceDependency
from fixbackend.cloud_accounts.gcp_service_account_repo import GcpServiceAccountKeyRepository
from fixbackend.cloud_accounts.gcp_service_account_service import GcpServiceAccountService
from fixbackend.dependencies import FixDependencies, ServiceNames
from fixbackend.inventory.inventory_service import InventoryService
from fixbackend.inventory.inventory_router import CurrentGraphDbDependency
from fixbackend.permissions.models import WorkspacePermissions
from fixbackend.permissions.permission_checker import WorkspacePermissionChecker
from fixbackend.cloud_accounts.models import CloudAccountStates
from fixbackend.cloud_accounts.schemas import (
    AwsCloudAccountUpdate,
    AwsCloudFormationLambdaCallbackParameters,
    AzureSubscriptionCredentialsRead,
    AzureSubscriptionCredentialsUpdate,
    CloudAccountList,
    CloudAccountRead,
    GcpServiceAccountKeyRead,
    LastScanInfo,
    ScannedAccount,
)
from fixbackend.fix_jwt import JwtService
from fixbackend.ids import FixCloudAccountId, WorkspaceId
from fixbackend.logging_context import set_cloud_account_id, set_workspace_id
from fixbackend.streaming_response import StreamOnSuccessResponse, streaming_response
from fixbackend.workspaces.dependencies import UserWorkspaceDependency

log = logging.getLogger(__name__)


audience = "azure_oauth_endpoint"


class AzureSetupStep(StrEnum):
    admin_consent = "admin_consent"
    get_management_credentials = "get_management_credentials"

    def __str__(self) -> str:
        return self.value


def cloud_accounts_router(dependencies: FixDependencies) -> APIRouter:
    router = APIRouter()

    jwt_service = dependencies.service(ServiceNames.jwt_service, JwtService)

    gcp_service_account_repo = dependencies.service(
        ServiceNames.gcp_service_account_repo, GcpServiceAccountKeyRepository
    )

    gcp_service_account_service = dependencies.service(
        ServiceNames.gcp_service_account_service, GcpServiceAccountService
    )

    azure_subscription_repo = dependencies.service(
        ServiceNames.azure_subscription_repo, AzureSubscriptionCredentialsRepository
    )

    azure_subscription_service = dependencies.service(ServiceNames.azure_subscription_service, AzureSubscriptionService)

    def inventory() -> InventoryService:
        return dependencies.service(ServiceNames.inventory, InventoryService)

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

    @router.put("/{workspace_id}/cloud_accounts/gcp/key")
    async def add_gcp_service_account_key(
        workspace: UserWorkspaceDependency,
        service_account_key: Annotated[
            bytes, File(description="GCP's service_account.json file", max_length=64 * 1024)
        ],
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update_cloud_accounts))],
    ) -> Response:

        try:
            string_key = service_account_key.decode("utf-8")
            json.loads(service_account_key)
        except Exception as e:
            log.error(f"Error decoding GCP service account key: {e}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_json")

        try:
            await gcp_service_account_service.list_projects(string_key)
        except MalformedError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_json")
        except HttpError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e.reason))
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

        await gcp_service_account_repo.upsert(workspace.id, string_key)

        return Response(status_code=201)

    @router.get("/{workspace_id}/cloud_accounts/gcp/key")
    async def get_gcp_service_account_keys(
        workspace: UserWorkspaceDependency,
    ) -> GcpServiceAccountKeyRead:
        key = await gcp_service_account_repo.get_by_tenant(workspace.id)
        if key is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no_key_found")
        return GcpServiceAccountKeyRead.from_model(key)

    @router.put("/{workspace_id}/cloud_accounts/azure/credentials")
    async def add_azure_subscription_credentials(
        workspace: UserWorkspaceDependency,
        credentials: AzureSubscriptionCredentialsUpdate,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update_cloud_accounts))],
    ) -> Response:

        try:
            await azure_subscription_service.list_subscriptions(
                credentials.azure_tenant_id, credentials.client_id, credentials.client_secret
            )
        except Exception as e:
            log.info(f"Error listing Azure subscriptions: {e}")
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_credentials")

        await azure_subscription_repo.upsert(
            workspace.id,
            credentials.azure_tenant_id,
            credentials.client_id,
            credentials.client_secret,
        )

        return Response(status_code=201)

    @router.get("/{workspace_id}/cloud_accounts/azure/credentials")
    async def get_azure_credentials(
        workspace: UserWorkspaceDependency,
    ) -> AzureSubscriptionCredentialsRead:
        creds = await azure_subscription_repo.get_by_tenant(workspace.id)
        if creds is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no_credentials_found")
        return AzureSubscriptionCredentialsRead.from_model(creds)

    @router.get("/{workspace_id}/cloud_account/azure/setup")
    async def azure_admin_consent(request: Request, workspace: UserWorkspaceDependency) -> Response:

        client_id = dependencies.config.azure_client_id

        payload = {
            "workspace_id": f"{workspace.id}",
            "step": AzureSetupStep.admin_consent,
        }

        state = await jwt_service.encode(payload, [audience])

        redirect_url = request.url_for("azure_oauth_callback")

        url = f"https://login.microsoftonline.com/organizations/adminconsent?client_id={client_id}&state={state}&redirect_uri={redirect_url}"

        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)

    @router.get("/{workspace_id}/cloud_account/{cloud_account_id}/logs", tags=["report"])
    async def logs(
        workspace: UserWorkspaceDependency,
        cloud_account_id: FixCloudAccountId,
        service: CloudAccountServiceDependency,
        graph_db: CurrentGraphDbDependency,
        request: Request,
    ) -> StreamOnSuccessResponse:
        fn, media_type = streaming_response(request.headers.get("accept", "application/json"))

        cloud_account = await service.get_cloud_account(cloud_account_id, workspace.id)
        if cloud_account is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="cloud_account_not_found")

        task_id = cloud_account.last_task_id
        if task_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no_task_id")

        async def stream() -> AsyncIterator[str]:
            async with inventory().logs(graph_db, task_id) as result:
                async for elem in fn(result):
                    yield elem

        return StreamOnSuccessResponse(stream(), media_type=media_type)

    return router


def cloud_accounts_callback_router(dependencies: FixDependencies) -> APIRouter:
    router = APIRouter()

    authority = "https://login.microsoftonline.com/common"  # for multi-tenant apps

    config = dependencies.config
    jwt_service = dependencies.service(ServiceNames.jwt_service, JwtService)
    azure_subscription_service = dependencies.service(ServiceNames.azure_subscription_service, AzureSubscriptionService)

    azure_app = ConfidentialClientApplication(
        client_id=config.azure_client_id, authority=authority, client_credential=config.azure_client_secret
    )

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

    @router.get("/callbacks/azure/oauth", name="azure_oauth_callback")
    async def azure_oauth_callback(
        request: Request, state: str, tenant: Optional[str] = None, code: Optional[str] = None
    ) -> Response:

        def redirect_to_ui(location: str = "/") -> Response:
            response = Response()
            response.headers["location"] = "/"
            response.status_code = status.HTTP_303_SEE_OTHER
            return response

        payload = await jwt_service.decode(state, [audience])
        if payload is None:
            return redirect_to_ui()

        if ws_id := payload.get("workspace_id"):
            ws_uuid = UUID(ws_id)
            workspace_id = WorkspaceId(ws_uuid)
        else:
            return redirect_to_ui()

        match payload.get("step"):
            case AzureSetupStep.admin_consent:
                if not tenant:
                    redirect_to_ui()

                management_scopes = ["https://management.azure.com/user_impersonation"]

                payload = dict(payload)
                payload["step"] = AzureSetupStep.get_management_credentials
                payload["azure_tenant_id"] = tenant

                state = await jwt_service.encode(payload, [audience])
                url = azure_app.get_authorization_request_url(
                    scopes=management_scopes,
                    redirect_uri=f"{request.url_for("azure_oauth_callback")}",
                    state=state,
                )
                return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)

            case AzureSetupStep.get_management_credentials:
                if code is None:
                    return redirect_to_ui()

                azure_tenant_id = payload.get("azure_tenant_id")
                if azure_tenant_id is None:
                    return redirect_to_ui()

                credential = AuthorizationCodeCredential(
                    tenant_id=config.azure_tenant_id,
                    client_id=config.azure_client_id,
                    client_secret=config.azure_client_secret,
                    authorization_code=code,
                    redirect_uri=f"{request.url_for("azure_oauth_callback")}",
                    additionally_allowed_tenants=["*"],
                )

                creds = await azure_subscription_service.create_user_app_registration(
                    workspace_id, azure_tenant_id, credential
                )

                if creds is None:
                    return redirect_to_ui()

                return redirect_to_ui()

            case _:
                return redirect_to_ui()

    return router
