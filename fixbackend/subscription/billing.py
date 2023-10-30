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
from typing import Any, Optional

from fixcloudutils.asyncio import stop_running_task
from fixcloudutils.service import Service
from fixcloudutils.util import utc

from fixbackend.subscription.aws_marketplace import AwsMarketplaceHandler
from fixbackend.subscription.models import SubscriptionMethod
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.utils import kill_running_process

log = logging.getLogger(__name__)


class BillingService(Service):
    def __init__(self, aws_marketplace: AwsMarketplaceHandler, subscription_repository: SubscriptionRepository) -> None:
        self.aws_marketplace = aws_marketplace
        self.subscription_repository = subscription_repository
        self.handler: Optional[Task[Any]] = None

    async def start(self) -> Any:
        self.handler = asyncio.create_task(self.handle_outstanding_subscriptions())

    async def stop(self) -> Any:
        await stop_running_task(self.handler)

    async def handle_outstanding_subscriptions(self) -> None:
        try:
            log.info("Create overdue billing entries")
            await self.create_overdue_billing_entries()
            log.info("Report usages to AWS Marketplace")
            await self.aws_marketplace.report_unreported_usages()
        finally:
            kill_running_process()

    async def create_overdue_billing_entries(self) -> None:
        semaphore = asyncio.Semaphore(16)
        async with TaskGroup() as group:
            async for subscription in self.subscription_repository.subscriptions(
                active=True, next_charge_timestamp_younger_than=utc()
            ):
                async with semaphore:
                    group.create_task(self.create_billing_entry(subscription))

    async def create_billing_entry(self, subscription: SubscriptionMethod) -> None:
        try:
            await self.aws_marketplace.create_billing_entry(subscription)
        except Exception as e:
            log.error(f"Failed to create billing entry for subscription {subscription.id}: {e}. Ignore.", exc_info=True)
