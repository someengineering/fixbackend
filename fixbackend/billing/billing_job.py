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

import prometheus_client
from fixcloudutils.asyncio import stop_running_task
from fixcloudutils.service import Service
from fixcloudutils.util import utc

from fixbackend.billing.service import BillingEntryService
from fixbackend.config import Config
from fixbackend.ids import BillingId
from fixbackend.subscription.aws_marketplace import AwsMarketplaceHandler
from fixbackend.subscription.models import SubscriptionMethod, BillingEntry, AwsMarketplaceSubscription
from fixbackend.subscription.stripe_subscription import StripeService
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.utils import kill_running_process, uid
from fixbackend.workspaces.repository import WorkspaceRepository

log = logging.getLogger(__name__)


class BillingJob(Service):
    def __init__(
        self,
        aws_marketplace: AwsMarketplaceHandler,
        stripe_service: StripeService,
        subscription_repository: SubscriptionRepository,
        workspace_repository: WorkspaceRepository,
        billing_entry_service: BillingEntryService,
        config: Config,
    ) -> None:
        self.aws_marketplace = aws_marketplace
        self.stripe_service = stripe_service
        self.subscription_repository = subscription_repository
        self.workspace_repository = workspace_repository
        self.handler: Optional[Task[Any]] = None
        self.config = config
        self.billing_entry_service = billing_entry_service

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
            log.info("Report usages to Stripe")
            await self.stripe_service.report_unreported_usages()
            log.info("Report no usage for all active AWS Marketplace subscriptions")
            await self.report_no_usage_for_active_aws_marketplace_subscriptions(now, parallel_requests)
            await self.push_metrics()
        finally:
            kill_running_process()

    async def push_metrics(self) -> None:
        if gateway := self.config.push_gateway_url:
            await asyncio.to_thread(
                lambda: prometheus_client.push_to_gateway(
                    gateway=gateway, job="fixbackend-billing-hourly", registry=prometheus_client.REGISTRY
                )
            )
            log.info("Metrics pushed to gateway")

    async def create_overdue_billing_entries(self, now: datetime, parallel_requests: int) -> None:
        semaphore = asyncio.Semaphore(parallel_requests)
        counter = 0

        async def create_billing_entry(subscription: SubscriptionMethod) -> None:
            try:
                async with semaphore:
                    if await self.billing_entry_service.create_billing_entry(subscription):
                        nonlocal counter
                        counter += 1
            except Exception as e:
                log.error(
                    f"Failed to create billing entry for subscription {subscription.id}: {e}. Ignore.", exc_info=True
                )

        async with TaskGroup() as group:
            async for sub in self.subscription_repository.subscriptions(active=True, next_charge_timestamp_before=now):
                group.create_task(create_billing_entry(sub))
        if counter > 0:
            log.info(f"Created {counter} overdue billing entries")

    async def report_no_usage_for_active_aws_marketplace_subscriptions(
        self, now: datetime, parallel_requests: int
    ) -> None:
        semaphore = asyncio.Semaphore(parallel_requests)

        async def chunked_subscriptions(
            size: int,
        ) -> AsyncIterator[List[Tuple[AwsMarketplaceSubscription, BillingEntry]]]:
            chunk: List[Tuple[AwsMarketplaceSubscription, BillingEntry]] = []
            async for subscription in self.subscription_repository.subscriptions(
                active=True, is_aws_marketplace_subscription=True, next_charge_timestamp_after=now
            ):
                assert isinstance(
                    subscription, AwsMarketplaceSubscription
                ), f"Expected AwsMarketplaceSubscription, but got {subscription}"
                for workspace in await self.workspace_repository.list_workspaces_by_subscription_id(subscription.id):
                    # create a dummy billing entry with no usage
                    entry = BillingEntry(
                        id=BillingId(uid()),
                        workspace_id=workspace.id,
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

        async def report_usages(chunk: List[Tuple[AwsMarketplaceSubscription, BillingEntry]]) -> None:
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
