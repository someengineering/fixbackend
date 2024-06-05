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
from datetime import timedelta
from typing import Any, List, Optional
from attr import frozen
from fixcloudutils.service import Service
from fixbackend.cloud_accounts.azure_subscription_repo import AzureSubscriptionCredentialsRepository
from fixbackend.cloud_accounts.models import AzureSubscriptionCredentials
from fixbackend.cloud_accounts.service import CloudAccountService
from fixbackend.ids import AzureSubscriptionCredentialsId, CloudAccountId, CloudAccountName, WorkspaceId

from fixcloudutils.asyncio.periodic import Periodic
from fixcloudutils.util import utc
from logging import getLogger

from azure.identity import ClientSecretCredential
from azure.mgmt.resource import SubscriptionClient

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
        dispatching: bool = False,
    ) -> None:
        self.dispatching = dispatching
        self.azure_subscriptions_repo = azure_subscriptions_repo
        self.cloud_account_service = cloud_account_service
        self.new_subscription_pinger = Periodic(
            "new_subscription_pinger", self._ping_new_subscriptions, timedelta(minutes=1)
        )

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
        try:
            subscriptions = await self.list_subscriptions(creds.azure_tenant_id, creds.client_id, creds.client_secret)
        except Exception as e:
            log.info(f"Failed to list azure subscriptions, credential_id {creds.id}, marking it as invalid: {e}")
            await self.azure_subscriptions_repo.update_status(creds.id, can_access_accounts=False)
            return None
        await self.azure_subscriptions_repo.update_status(creds.id, can_access_accounts=True)
        await self.update_cloud_accounts(subscriptions, creds.tenant_id, creds.id)

    async def _ping_new_subscriptions(self) -> None:
        created_less_than_30_minutes_ago = await self.azure_subscriptions_repo.list_created_after(
            utc() - timedelta(minutes=30)
        )

        async with asyncio.TaskGroup() as tg:
            for azure_credential in created_less_than_30_minutes_ago:
                tg.create_task(self._import_subscriptions(azure_credential))
