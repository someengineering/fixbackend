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
from asyncio import Semaphore, TaskGroup
from datetime import timedelta, datetime
from typing import Annotated, Any, Literal, Optional, Tuple, List
from uuid import uuid4

import boto3
from fastapi import Depends
from fixcloudutils.asyncio.async_extensions import run_async
from fixcloudutils.service import Service
from fixcloudutils.types import Json
from fixcloudutils.util import utc, utc_str

from fixbackend.auth.models import User
from fixbackend.dependencies import FixDependency, ServiceNames
from fixbackend.domain_events.events import AwsMarketplaceSubscriptionCreated, BillingEntryCreated
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.ids import SecurityTier, SubscriptionId
from fixbackend.metering.metering_repository import MeteringRepository
from fixbackend.sqs import SQSRawListener
from fixbackend.subscription.models import AwsMarketplaceSubscription, SubscriptionMethod, BillingEntry
from fixbackend.subscription.subscription_repository import (
    SubscriptionRepository,
)
from fixbackend.utils import start_of_next_period
from fixbackend.workspaces.repository import WorkspaceRepository
from prometheus_client import Counter

log = logging.getLogger(__name__)


def compute_billing_period_factor(
    *,
    billing_time: datetime,
    last_charged: datetime,
    period_value: timedelta,
) -> float:
    delta = billing_time - last_charged
    # Default should be a single month. For shorter or longer periods, we use a fraction/factor of the month
    period_lower_bound = period_value - period_value * 0.1667  # - 5 days in case of 30 days
    period_upper_bound = period_value + period_value * 0.1667  # + 5 days in case of 30 days
    is_full_period = period_lower_bound < delta < period_upper_bound
    billing_factor = 1.0 if is_full_period else delta / period_value
    return billing_factor


AccountsCharged = Counter("aws_marketplace_accounts_charged", "Accounts charged by security tier", ["security_tier"])


class AwsMarketplaceHandler(Service):
    def __init__(
        self,
        subscription_repo: SubscriptionRepository,
        workspace_repo: WorkspaceRepository,
        metering_repo: MeteringRepository,
        session: boto3.Session,
        sqs_queue_url: Optional[str],
        domain_event_sender: DomainEventPublisher,
        billing_period: Literal["month", "day"],
    ) -> None:
        self.subscription_repo = subscription_repo
        self.workspace_repo = workspace_repo
        self.metering_repo = metering_repo
        self.listener = (
            SQSRawListener(
                session,
                sqs_queue_url,
                self.handle_message,
                consider_failed_after=timedelta(minutes=5),
                max_nr_of_messages_in_one_batch=1,
                wait_for_new_messages_to_arrive=timedelta(seconds=10),
            )
            if sqs_queue_url is not None
            else None
        )
        self.marketplace_client: Any = session.client("meteringmarketplace")
        self.domain_event_sender = domain_event_sender
        self.billing_period: Literal["month", "day"] = billing_period

    async def start(self) -> None:
        if self.listener is not None:
            await self.listener.start()

    async def stop(self) -> None:
        if self.listener is not None:
            await self.listener.stop()

    async def subscribed(self, user: User, token: str) -> SubscriptionMethod:
        log.info(f"AWS Marketplace subscription for user {user.email} with token {token}")
        # Get the related data from AWS. Will throw in case of an error.
        customer_data = self.marketplace_client.resolve_customer(RegistrationToken=token)
        log.debug(f"AWS Marketplace user {user.email} got customer data: {customer_data}")
        product_code = customer_data["ProductCode"]
        customer_identifier = customer_data["CustomerIdentifier"]
        customer_aws_account_id = customer_data["CustomerAWSAccountId"]

        # get all workspaces of the user and use the first one if it is the only one
        # if more than one workspace exists, the user needs to define the workspace in a later step
        workspaces = await self.workspace_repo.list_workspaces(user.id)
        workspace_id = workspaces[0].id if len(workspaces) == 1 else None

        # only create a new subscription if there is no existing one
        if existing := await self.subscription_repo.aws_marketplace_subscription(user.id, customer_identifier):
            log.debug(f"AWS Marketplace user {user.email}: return existing subscription")
            return existing
        else:
            subscription = AwsMarketplaceSubscription(
                id=SubscriptionId(uuid4()),
                user_id=user.id,
                workspace_id=workspace_id,
                customer_identifier=customer_identifier,
                customer_aws_account_id=customer_aws_account_id,
                product_code=product_code,
                active=True,
                last_charge_timestamp=utc(),
                next_charge_timestamp=start_of_next_period(period=self.billing_period, hour=9),
            )
            event = AwsMarketplaceSubscriptionCreated(
                workspace_id=workspace_id, user_id=user.id, subscription_id=subscription.id
            )
            result = await self.subscription_repo.create(subscription)
            await self.domain_event_sender.publish(event)
            return result

    async def create_billing_entry(
        self, subscription: AwsMarketplaceSubscription, now: Optional[datetime] = None
    ) -> Optional[BillingEntry]:
        if not subscription.active:
            log.info(f"AWS Marketplace: subscription {subscription.id} is not active")
            return None
        try:
            billing_time = now or utc()

            next_charge = start_of_next_period(period=self.billing_period, current_time=billing_time, hour=9)
            match self.billing_period:
                case "month":
                    billing_period_value = timedelta(days=30)
                case "day":
                    billing_period_value = timedelta(days=1)

            last_charged = subscription.last_charge_timestamp or billing_time
            customer = subscription.customer_identifier

            month_factor = compute_billing_period_factor(
                billing_time=billing_time,
                last_charged=last_charged,
                period_value=billing_period_value,
            )
            if ws_id := subscription.workspace_id:
                # Get the summaries for the last period, with at least 100 resources collected and at least 3 collects
                summaries = [
                    summary
                    async for summary in self.metering_repo.collect_summary(
                        ws_id, start=last_charged, end=billing_time, min_resources_collected=100, min_nr_of_collects=3
                    )
                ]
                tiers = [summary.security_tier for summary in summaries]
                # highest recorded tier
                security_tier = max(tiers)
                # We only count the number of accounts, no matter how many runs we had
                usage = int(len(summaries) * month_factor)
                if security_tier == SecurityTier.Free or usage == 0:
                    log.info(f"AWS Marketplace: customer {customer} has no usage")
                    # move the charge timestamp tp
                    await self.subscription_repo.update_charge_timestamp(subscription.id, billing_time, next_charge)
                    return None
                log.info(f"AWS Marketplace: customer {customer} collected {usage} times: {summaries}")
                AccountsCharged.labels(security_tier=security_tier.value).inc(usage)
                billing_entry = await self.subscription_repo.add_billing_entry(
                    subscription.id,
                    subscription.workspace_id,
                    security_tier,
                    usage,
                    last_charged,
                    billing_time,
                    next_charge,
                )
                await self.domain_event_sender.publish(
                    BillingEntryCreated(subscription.workspace_id, subscription.id, security_tier, usage)
                )
                return billing_entry
            else:
                log.info(f"AWS Marketplace: customer {customer} has no workspace")
                return None
        except Exception:
            log.error("Could not create a billing entry", exc_info=True)
            raise

    async def report_usage(
        self, product_code: str, entries: List[Tuple[AwsMarketplaceSubscription, BillingEntry]]
    ) -> None:
        result = await run_async(
            self.marketplace_client.batch_meter_usage,
            ProductCode=product_code,
            UsageRecords=[
                dict(
                    CustomerIdentifier=subscription.customer_identifier,
                    Dimension=entry.tier.value,
                    Quantity=entry.nr_of_accounts_charged,
                    Timestamp=utc_str(entry.period_end),
                )
                for subscription, entry in entries
            ],
        )
        if len(result.get("UnprocessedRecords", [])) > 0:
            raise ValueError(f"Could not report usage for billing entries {result}")

    async def report_unreported_usages(self, raise_exception: bool = False) -> None:
        async def send(be: BillingEntry, ms: AwsMarketplaceSubscription) -> None:
            try:
                await self.report_usage(ms.product_code, [(ms, be)])
                await self.subscription_repo.mark_billing_entry_reported(entry.id)
            except Exception:
                log.error(f"Could not report usage for billing entry {be.id}", exc_info=True)
                if raise_exception:
                    raise

        max_parallel = Semaphore(64)  # up to 64 parallel tasks
        async with TaskGroup() as group:
            async for entry, subscription in self.subscription_repo.unreported_billing_entries():
                async with max_parallel:
                    await group.create_task(send(entry, subscription))

    async def subscription_canceled(self, customer_id: str) -> None:
        async for subscription in self.subscription_repo.subscriptions(aws_customer_identifier=customer_id):
            if billing := await self.create_billing_entry(subscription):
                await self.report_usage(subscription.product_code, [(subscription, billing)])

    async def handle_message(self, message: Json) -> None:
        # See: https://docs.aws.amazon.com/marketplace/latest/userguide/saas-notification.html
        log.info(f"AWS Marketplace. Received message: {message}")
        body = json.loads(message["Body"])
        action = body["action"]
        customer_identifier = body["customer-identifier"]
        # product_code = body["product-code"]
        # free_trial = body.get("isFreeTrialTermPresent", False)
        match action:
            case "subscribe-success":
                # allow sending metering records
                count = await self.subscription_repo.mark_aws_marketplace_subscriptions(customer_identifier, True)
                log.info(
                    f"AWS Marketplace. subscribe-success for customer {customer_identifier}. "
                    f"Updated {count} subscriptions."
                )
            case "unsubscribe-pending":
                log.info(f"AWS Marketplace: subscription canceled for customer {customer_identifier}. Report usage.")
                await self.subscription_canceled(customer_identifier)
            case "subscribe-fail" | "unsubscribe-success":
                count = await self.subscription_repo.mark_aws_marketplace_subscriptions(customer_identifier, False)
                log.info(
                    f"AWS Marketplace. subscribe-success for customer {customer_identifier}. "
                    f"Updated {count} subscriptions."
                )
            case _:
                raise ValueError(f"Unknown action: {action}")


def get_marketplace_handler(deps: FixDependency) -> AwsMarketplaceHandler:
    return deps.service(ServiceNames.aws_marketplace_handler, AwsMarketplaceHandler)


AwsMarketplaceHandlerDependency = Annotated[AwsMarketplaceHandler, Depends(get_marketplace_handler)]
