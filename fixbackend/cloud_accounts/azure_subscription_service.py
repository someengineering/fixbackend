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
from uuid import uuid4
import warnings
from datetime import timedelta
from logging import getLogger
from typing import Any, List, Optional, Dict, Set

from attr import frozen
from azure.identity.aio import ClientSecretCredential
from azure.mgmt.resource.subscriptions.aio import SubscriptionClient
from fixcloudutils.asyncio.periodic import Periodic
from fixcloudutils.service import Service
from fixcloudutils.util import utc
from azure.core.credentials_async import AsyncTokenCredential

from msgraph import GraphServiceClient
from msgraph.generated.models.application import Application
from msgraph.generated.models.password_credential import PasswordCredential
from msgraph.generated.applications.item.add_password.add_password_post_request_body import AddPasswordPostRequestBody
from msgraph.generated.models.service_principal import ServicePrincipal
from azure.mgmt.authorization.aio import AuthorizationManagementClient
from azure.mgmt.authorization.models import RoleAssignmentCreateParameters
from azure.mgmt.resourcegraph.aio import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest
import networkx as nx

from azure.mgmt.managementgroups.aio import ManagementGroupsAPI

from fixbackend.cloud_accounts.azure_subscription_repo import AzureSubscriptionCredentialsRepository
from fixbackend.cloud_accounts.models import AzureSubscriptionCredentials
from fixbackend.cloud_accounts.service import CloudAccountService
from fixbackend.config import Config
from fixbackend.ids import AzureSubscriptionCredentialsId, CloudAccountId, CloudAccountName, WorkspaceId
from fixbackend.logging_context import set_workspace_id

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

        credential = ClientSecretCredential(tenant_id=azure_tenant_id, client_id=client_id, client_secret=client_secret)
        subscription_client = SubscriptionClient(credential)
        subscriptions = subscription_client.subscriptions.list()

        subscription_infos = []

        async for subscription in subscriptions:
            if subscription.subscription_id:
                subscription_infos.append(
                    SubscriptionInfo(
                        subscription_id=subscription.subscription_id,
                        subscription_name=subscription.display_name,
                    )
                )

        return subscription_infos

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
        self,
        workspace_id: WorkspaceId,
        azure_tenant_id: str,
        management_credential: AsyncTokenCredential,
    ) -> Optional[AzureSubscriptionCredentials]:

        set_workspace_id(workspace_id)

        async def create_role_assignment(
            auth_managemement_client: AuthorizationManagementClient,
            service_principal_id: str,
            scope: str,
            role_definition_id: str,
        ) -> bool:
            role_assignment_params = RoleAssignmentCreateParameters(
                role_definition_id=role_definition_id,
                principal_id=service_principal_id,
                principal_type="ServicePrincipal",
            )  # type: ignore

            try:
                role_assignment = await auth_managemement_client.role_assignments.create(
                    scope=scope,
                    role_assignment_name=str(uuid4()),
                    parameters=role_assignment_params,
                )
                log.info("Created role assignment: %s", role_assignment.id)
                return True
            except Exception as e:
                log.info("Failed to create role assignment")
                log.info(e, exc_info=True)
                return False

        fix_client_id = self.config.azure_client_id
        fix_client_secret = self.config.azure_client_secret
        fix_azure_tenant_id = self.config.azure_tenant_id

        service_principal_credentials = ClientSecretCredential(
            tenant_id=fix_azure_tenant_id, client_id=fix_client_id, client_secret=fix_client_secret
        )

        graph_client = GraphServiceClient(service_principal_credentials)

        # new app registration definition
        app = Application(
            display_name=f"Fix Access for Workspace {workspace_id}",
            sign_in_audience="AzureADMyOrg",  # see https://learn.microsoft.com/en-us/entra/identity-platform/supported-accounts-validation#validation-differences
        )

        try:
            # create the tenant-specific app registration
            created_app = await graph_client.applications.post(app)
            if created_app is None:
                log.error("Failed to create app registration: created_app is None")
                return None

            if created_app.id is None:
                log.error("Failed to create app registration: id is None")
                return None

            if created_app.app_id is None:
                log.error("Failed to create app registration: app_id is None")
                return None
            log.info(f"created app registration, app_id: {created_app.app_id}")

            # create a secret for the app registration
            password_credential = AddPasswordPostRequestBody(
                password_credential=PasswordCredential(
                    display_name="Fix Access Client Secret",
                    end_date_time=utc() + (timedelta(days=365) * 10),  # 10 years
                )
            )
            log.info("created password_credential")
            secrets = await graph_client.applications.by_application_id(created_app.id).add_password.post(
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
            service_principal_id = service_principal.id
            if service_principal_id is None:
                log.error("Failed to create app registration: service_principal_id is None")
                return None
            log.info("created service principal")

            # list all subscriptions
            subscription_client = SubscriptionClient(management_credential)
            subscriptions = []
            async for subscription in subscription_client.subscriptions.list():
                subscriptions.append(subscription)

            # list all management groups
            management_groups_api = ManagementGroupsAPI(management_credential)
            management_groups = []
            async for group in management_groups_api.management_groups.list():
                management_groups.append(group)

            # list the subscriptions ancestors
            resource_graph_client = ResourceGraphClient(management_credential)
            query = """
            resourcecontainers
            | where type == 'microsoft.resources/subscriptions'
            | project name, id, properties.managementGroupAncestorsChain
            """

            request = QueryRequest(query=query)

            response = await resource_graph_client.resources(request)
            sub_ancestors: List[Dict[str, Any]] = response.data

            # management group id from name
            def mg_id(name: str) -> str:
                return f"/providers/Microsoft.Management/managementGroups/{name}"

            G = nx.DiGraph()
            for mg in management_groups:
                G.add_node(mg.id, type="mg")

            for sub in sub_ancestors:
                G.add_node(sub["id"], type="sub")
                # ancestors are in order from root to leaf, so reverse them
                ancestors = list(sub["properties_managementGroupAncestorsChain"])
                ancestors.reverse()
                for i in range(len(ancestors)):
                    ancestor = ancestors[i]
                    # add edge from ancestor to subscription
                    if i == 0:
                        G.add_edge(mg_id(ancestor["name"]), sub["id"])
                    # add edge from ancestor to previous ancestor
                    if i > 0:
                        prev = ancestors[i - 1]
                        G.add_edge(mg_id(ancestor["name"]), mg_id(prev["name"]))

            async def assign_role_dfs(node_id: str, already_assigned: bool, visited_nodes: Set[str]) -> None:
                if node_id in visited_nodes:
                    return
                visited_nodes.add(node_id)

                assigned = already_assigned

                if not already_assigned:
                    assigned = await create_role_assignment(
                        auth_client, service_principal_id, node_id, reader_role_definition_id
                    )
                    if assigned:
                        log.info("Created role assignment for %s", node_id)

                for child in G.successors(node_id):
                    await assign_role_dfs(child, assigned, visited_nodes)

            subscription_id: str = subscriptions[0].id
            auth_client = AuthorizationManagementClient(management_credential, subscription_id)
            reader_role_definition_id = (
                "/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7"
            )

            # find the graph root (or whatever is at the top of the hierarchy)
            topological_order = list(nx.topological_sort(G))
            visited: Set[str] = set()

            # traverse the groups/subscriptions tree and assign the reader role to the service principal
            for node in topological_order:
                await assign_role_dfs(node, False, visited)
            # test access by listing subscriptions as the new service principal
            subscription_client = SubscriptionClient(service_principal_credentials)
            principal_subscriptions = []
            async for sub in subscription_client.subscriptions.list():
                principal_subscriptions.append(sub)
            if not principal_subscriptions:
                log.error("Failed to create app registration: no subscriptions found")
                return None

        except Exception as e:
            log.error("Failed to create app registration")
            log.error(e, exc_info=True)
            return None

        result = await self.azure_subscriptions_repo.upsert(
            tenant_id=workspace_id,
            azure_tenant_id=azure_tenant_id,
            client_id=created_app.app_id,
            client_secret=secrets.secret_text,
        )

        log.info(f"Created app registration for tenant {azure_tenant_id} with client_id {created_app.app_id}")

        return result
