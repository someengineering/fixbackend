from datetime import timedelta
from typing import Dict, Any, List, Tuple

from fixbackend.metering.metering_repository import MeteringRepository
from fixbackend.subscription.billing import BillingService
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.workspaces.models import Workspace
from tests.fixbackend.metering.metering_repository_test import create_metering_record


async def test_report_usage(
    subscription_repository: SubscriptionRepository,
    subscription: AwsMarketplaceSubscription,
    billing_service: BillingService,
    metering_repository: MeteringRepository,
    workspace: Workspace,
) -> None:
    assert subscription.next_charge_timestamp
    after_next_charge = subscription.next_charge_timestamp + timedelta(days=1)
    before_next_charge = subscription.next_charge_timestamp - timedelta(days=1)
    assert len([n async for n in subscription_repository.unreported_billing_entries()]) == 0
    await metering_repository.add(
        [create_metering_record(workspace_id=workspace.id, account_id="acc1") for _ in range(4)]
    )
    # before next charge: no billing entry is created
    await billing_service.create_overdue_billing_entries(before_next_charge, 16)
    assert len([n async for n in subscription_repository.unreported_billing_entries()]) == 0
    # after next charge: one billing entry is created
    await billing_service.create_overdue_billing_entries(after_next_charge, 16)
    assert len([n async for n in subscription_repository.unreported_billing_entries()]) == 1


async def test_report_no_usage(
    subscription: AwsMarketplaceSubscription,
    billing_service: BillingService,
    boto_answers: Dict[str, Any],
    boto_requests: List[Tuple[str, Any]],
) -> None:
    # BatchMeterUsage request is successful
    boto_answers["BatchMeterUsage"] = {
        "Results": [{"MeteringRecordId": "123", "Status": "Success"}],
        "UnprocessedRecords": [],
    }
    assert subscription.next_charge_timestamp
    before_next_charge = subscription.next_charge_timestamp - timedelta(days=1)
    after_next_charge = subscription.next_charge_timestamp + timedelta(days=1)
    # there is no subscription with no usage after next charge
    await billing_service.report_no_usage_for_active_subscriptions(after_next_charge, 16)
    assert len(boto_requests) == 0
    # there is one subscription that will be charged later
    await billing_service.report_no_usage_for_active_subscriptions(before_next_charge, 16)
    assert len(boto_requests) == 1
    assert boto_requests[0][0] == "BatchMeterUsage"
    # subscription is reported with no usage
    assert len(boto_requests[0][1]["UsageRecords"]) == 1
    first = boto_requests[0][1]["UsageRecords"][0]
    assert first["Quantity"] == 0
    assert first["CustomerIdentifier"] == subscription.customer_identifier
