#  Copyright (c) 2024. Some Engineering
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

import asyncio
from uuid import UUID, uuid4
import warnings
from datetime import timedelta
from logging import getLogger
from typing import Any, List, Optional

from attr import frozen
from azure.identity import ClientSecretCredential
from azure.mgmt.resource import SubscriptionClient
from fixcloudutils.asyncio.periodic import Periodic
from fixcloudutils.service import Service
from fixcloudutils.util import utc

from msgraph import GraphServiceClient
from msgraph.generated.models.application import Application
from msgraph.generated.models.password_credential import PasswordCredential
from msgraph.generated.applications.item.add_password.add_password_post_request_body import AddPasswordPostRequestBody
from msgraph.generated.models.required_resource_access import RequiredResourceAccess
from msgraph.generated.models.resource_access import ResourceAccess
from msgraph.generated.models.service_principal import ServicePrincipal
from azure.mgmt.authorization import AuthorizationManagementClient
from azure.mgmt.authorization.models import RoleAssignmentCreateParameters

from azure.mgmt.managementgroups import ManagementGroupsAPI

from fixbackend.cloud_accounts.azure_subscription_repo import AzureSubscriptionCredentialsRepository
from fixbackend.cloud_accounts.models import AzureSubscriptionCredentials
from fixbackend.cloud_accounts.service import CloudAccountService
from fixbackend.config import Config
from fixbackend.ids import AzureSubscriptionCredentialsId, CloudAccountId, CloudAccountName, WorkspaceId

log = getLogger(__name__)


@frozen
class SubscriptionInfo:
    subscription_id: str
    subscription_name: Optional[str]


class AzureSubscriptionService(Service):

    def __init__(
        self,
        azure_subscriptions_repo: AzureSubscriptionCredentialsRepository,
        cloud_account_service: CloudAccountService,
        config: Config,
        dispatching: bool = False,
    ) -> None:
        self.dispatching = dispatching
        self.azure_subscriptions_repo = azure_subscriptions_repo
        self.cloud_account_service = cloud_account_service
        self.new_subscription_pinger = Periodic(
            "new_subscription_pinger", self._ping_new_subscriptions, timedelta(minutes=1)
        )
        self.config = config

    async def start(self) -> Any:
        if self.dispatching:
            await self.new_subscription_pinger.start()

    async def stop(self) -> None:
        if self.dispatching:
            await self.new_subscription_pinger.stop()

    async def list_subscriptions(
        self, azure_tenant_id: str, client_id: str, client_secret: str
    ) -> List[SubscriptionInfo]:

        def blocking_call() -> List[SubscriptionInfo]:
            credential = ClientSecretCredential(
                tenant_id=azure_tenant_id, client_id=client_id, client_secret=client_secret
            )
            subscription_client = SubscriptionClient(credential)
            subscriptions = subscription_client.subscriptions.list()

            subscription_infos = []

            for subscription in subscriptions:
                if subscription.subscription_id:
                    subscription_infos.append(
                        SubscriptionInfo(
                            subscription_id=subscription.subscription_id,
                            subscription_name=subscription.display_name,
                        )
                    )

            return subscription_infos

        return await asyncio.to_thread(blocking_call)

    async def update_cloud_accounts(
        self,
        subscriptions: List[SubscriptionInfo],
        tenant_id: WorkspaceId,
        credentials_id: AzureSubscriptionCredentialsId,
    ) -> None:
        for subscription in subscriptions:

            await self.cloud_account_service.create_azure_account(
                workspace_id=tenant_id,
                account_id=CloudAccountId(subscription.subscription_id),
                subscription_credentials_id=credentials_id,
                account_name=(
                    CloudAccountName(subscription.subscription_name) if subscription.subscription_name else None
                ),
            )

    async def _import_subscriptions(self, creds: AzureSubscriptionCredentials) -> None:
        log.info(f"Importing azure subscriptions for credential_id {creds.id}")
        try:
            with warnings.catch_warnings(record=True) as captured_warnings:
                subscriptions = await self.list_subscriptions(
                    creds.azure_tenant_id, creds.client_id, creds.client_secret
                )
                for warning in captured_warnings:
                    log.info(warning.message, extra={"lineno": warning.lineno, "filename": warning.filename})

        except Exception as e:
            log.info(f"Failed to list azure subscriptions, credential_id {creds.id}, marking it as invalid: {e}")
            await self.azure_subscriptions_repo.update_status(creds.id, can_access_accounts=False)
            return None
        log.info("found %s subscriptions", len(subscriptions))
        await self.azure_subscriptions_repo.update_status(creds.id, can_access_accounts=True)
        await self.update_cloud_accounts(subscriptions, creds.tenant_id, creds.id)

    async def _ping_new_subscriptions(self) -> None:
        created_less_than_30_minutes_ago = await self.azure_subscriptions_repo.list_created_after(
            utc() - timedelta(minutes=30)
        )

        async with asyncio.TaskGroup() as tg:
            for azure_credential in created_less_than_30_minutes_ago:
                tg.create_task(self._import_subscriptions(azure_credential))

    async def create_user_app_registration(
        self, workspace_id: WorkspaceId, azure_tenant_id: str
    ) -> Optional[AzureSubscriptionCredentials]:
        fix_client_id = self.config.azure_client_id
        fix_client_secret = self.config.azure_client_secret

        credentials = ClientSecretCredential(
            tenant_id=azure_tenant_id, client_id=fix_client_id, client_secret=fix_client_secret
        )

        graph_client = GraphServiceClient(credentials)

        # required permissions for the app registration
        required_resource_access = [
            RequiredResourceAccess(
                resource_app_id="797f4846-ba00-4fd7-ba43-dac1f8f63013",  # Azure Service Management API, see https://learn.microsoft.com/en-us/troubleshoot/azure/entra/entra-id/governance/verify-first-party-apps-sign-in#application-ids-of-commonly-used-microsoft-applications
                resource_access=[
                    ResourceAccess(
                        id=UUID("41094075-9dad-400e-a0bd-54e686782033"),  # user_impersonation permission ID
                        type="Scope",
                    )
                ],
            )
        ]

        # new app registration definition
        app = Application(
            display_name=f"Fix Access {azure_tenant_id}",
            sign_in_audience="AzureADMyOrg",  # see https://learn.microsoft.com/en-us/entra/identity-platform/supported-accounts-validation#validation-differences
            required_resource_access=required_resource_access,
        )

        try:
            # create the tenant-specific app registration
            created_app = await graph_client.applications.post(app)
            if created_app is None:
                log.error("Failed to create app registration: created_app is None")
                return None

            if created_app.app_id is None:
                log.error("Failed to create app registration: app_id is None")
                return None

            # create a secret for the app registration
            password_credential = AddPasswordPostRequestBody(
                password_credential=PasswordCredential(
                    display_name="Fix Access Client Secret",
                    end_date_time=utc() + (timedelta(days=365) * 10),  # 10 years
                )
            )
            secrets = await graph_client.applications.by_application_id(created_app.app_id).add_password.post(
                password_credential
            )
            if secrets is None:
                log.error("Failed to create app registration: secrets is None")
                return None

            if secrets.secret_text is None:
                log.error("Failed to create app registration: secret_text is None")
                return None

            # create a service principal for the new app
            service_principal = await graph_client.service_principals.post(
                body=ServicePrincipal(app_id=created_app.app_id)
            )
            if service_principal is None:
                log.error("Failed to create app registration: service_principal is None")
                return None

            # get the root management group id
            management_client = ManagementGroupsAPI(credentials)
            tenant_details = await asyncio.to_thread(
                lambda: management_client.management_groups.get(group_id=azure_tenant_id)
            )
            root_management_group_id: str = tenant_details.id

            # get a subscription id associated with the tenant
            subscription_client = SubscriptionClient(credentials)
            subscriptions = await asyncio.to_thread(subscription_client.subscriptions.list)
            if not subscriptions:
                log.error("Failed to create app registration: no subscriptions found")
                return None

            # here we will get the first subscription id, I guess there is no difference
            subscription_id: Optional[str] = None

            def find_subscription_id() -> Optional[str]:
                for subscription in subscriptions:
                    if s_id := subscription.subscription_id:
                        return s_id  # type: ignore
                return None

            subscription_id = await asyncio.to_thread(find_subscription_id)

            if not subscription_id:
                log.error("Failed to create app registration: no subscription id found")
                return None

            # Create a reader role assignment between the app's service principal and the root management group
            auth_client = AuthorizationManagementClient(credentials, subscription_id)
            role_definition_id = "/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7"  # noqa, Reader role, see https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles#general
            role_assignment_params = RoleAssignmentCreateParameters(
                role_definition_id=role_definition_id,
                principal_id=service_principal.id,  # type: ignore
            )
            role_assignment = await asyncio.to_thread(
                lambda: auth_client.role_assignments.create(
                    scope=root_management_group_id,
                    role_assignment_name=str(uuid4()),
                    parameters=role_assignment_params,
                )
            )

            log.info("Created role assignment: %s", role_assignment.id)

        except Exception as e:
            log.error(f"Failed to create app registration: {e}")
            return None

        result = await self.azure_subscriptions_repo.upsert(
            tenant_id=workspace_id,
            azure_tenant_id=azure_tenant_id,
            client_id=created_app.app_id,
            client_secret=secrets.secret_text,
        )

        log.info(f"Created app registration for tenant {azure_tenant_id} with client_id {created_app.app_id}")

        return result
