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
import asyncio
import logging
from asyncio import Task, TaskGroup
from datetime import datetime
from typing import Any, Optional, AsyncIterator, List, Tuple

from fixcloudutils.asyncio import stop_running_task
from fixcloudutils.service import Service
from fixcloudutils.util import utc

from fixbackend.ids import BillingId
from fixbackend.subscription.aws_marketplace import AwsMarketplaceHandler
from fixbackend.subscription.models import SubscriptionMethod, BillingEntry
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.utils import kill_running_process, uid
from fixbackend.workspaces.repository import WorkspaceRepository

log = logging.getLogger(__name__)


class BillingService(Service):
    def __init__(
        self,
        aws_marketplace: AwsMarketplaceHandler,
        subscription_repository: SubscriptionRepository,
        workspace_repository: WorkspaceRepository,
    ) -> None:
        self.aws_marketplace = aws_marketplace
        self.subscription_repository = subscription_repository
        self.workspace_repository = workspace_repository
        self.handler: Optional[Task[Any]] = None

    async def start(self) -> Any:
        self.handler = asyncio.create_task(self.handle_outstanding_subscriptions())

    async def stop(self) -> Any:
        await stop_running_task(self.handler)

    # The billing service and so this method is started periodically every hour by a cron job.
    # All overdue billing entries will be created and reported to AWS Marketplace.
    # All active subscriptions that are not due for billing yet will be reported as no usage.
    async def handle_outstanding_subscriptions(self) -> None:
        try:
            now = utc()
            parallel_requests = 16
            log.info("Create overdue billing entries")
            await self.create_overdue_billing_entries(now, parallel_requests)
            log.info("Report usages to AWS Marketplace")
            await self.aws_marketplace.report_unreported_usages()
            log.info("Report no usage for all active subscriptions")
            await self.report_no_usage_for_active_subscriptions(now, parallel_requests)
        finally:
            kill_running_process()

    async def create_overdue_billing_entries(self, now: datetime, parallel_requests: int) -> None:
        semaphore = asyncio.Semaphore(parallel_requests)

        async def create_billing_entry(subscription: SubscriptionMethod) -> None:
            try:
                async with semaphore:
                    await self.aws_marketplace.create_billing_entry(subscription)
            except Exception as e:
                log.error(
                    f"Failed to create billing entry for subscription {subscription.id}: {e}. Ignore.", exc_info=True
                )

        async with TaskGroup() as group:
            async for subscription in self.subscription_repository.subscriptions(
                active=True, next_charge_timestamp_before=now
            ):
                group.create_task(create_billing_entry(subscription))

    async def report_no_usage_for_active_subscriptions(self, now: datetime, parallel_requests: int) -> None:
        semaphore = asyncio.Semaphore(parallel_requests)

        async def chunked_subscriptions(size: int) -> AsyncIterator[List[Tuple[SubscriptionMethod, BillingEntry]]]:
            chunk: List[Tuple[SubscriptionMethod, BillingEntry]] = []
            async for subscription in self.subscription_repository.subscriptions(
                active=True, next_charge_timestamp_after=now
            ):
                if workspace_id := subscription.workspace_id:
                    if workspace := await self.workspace_repository.get_workspace(workspace_id):
                        # create a dummy billing entry with no usage
                        entry = BillingEntry(
                            id=BillingId(uid()),
                            workspace_id=workspace_id,
                            subscription_id=subscription.id,
                            tier=workspace.product_tier,
                            nr_of_accounts_charged=0,
                            period_start=now,
                            period_end=now,
                            reported=False,
                        )
                        chunk.append((subscription, entry))
                        if len(chunk) >= size:
                            yield chunk
                            chunk = []
            if len(chunk) > 0:
                yield chunk

        async def report_usages(chunk: List[Tuple[SubscriptionMethod, BillingEntry]]) -> None:
            assert 0 < len(chunk) <= 25, f"Chunk size must be between 1 and 25, but got {len(chunk)}"
            product_code = chunk[0][0].product_code  # all subscriptions in a chunk have the same product code
            async with semaphore:
                try:
                    await self.aws_marketplace.report_usage(product_code, chunk)
                except Exception as ex:
                    log.warning(f"Error reporting no usage to AWS Marketplace: {ex}. Ignore.", exc_info=True)

        async with TaskGroup() as group:
            async for subscriptions in chunked_subscriptions(25):  # AWS Marketplace allows 25 subscriptions per request
                group.create_task(report_usages(subscriptions))
