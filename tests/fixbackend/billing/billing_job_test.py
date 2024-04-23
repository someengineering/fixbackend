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

from datetime import timedelta
from typing import Dict, Any, List, Tuple

from fixbackend.auth.models import User
from fixbackend.ids import ProductTier

from fixbackend.metering.metering_repository import MeteringRepository
from fixbackend.billing.billing_job import BillingJob
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository
from tests.fixbackend.metering.metering_repository_test import create_metering_record


async def test_report_usage(
    subscription_repository: SubscriptionRepository,
    aws_marketplace_subscription: AwsMarketplaceSubscription,
    billing_job: BillingJob,
    metering_repository: MeteringRepository,
    workspace_repository: WorkspaceRepository,
    workspace: Workspace,
) -> None:

    await workspace_repository.update_subscription(workspace.id, aws_marketplace_subscription.id)
    assert aws_marketplace_subscription.next_charge_timestamp
    after_next_charge = aws_marketplace_subscription.next_charge_timestamp + timedelta(days=1)
    before_next_charge = aws_marketplace_subscription.next_charge_timestamp - timedelta(days=1)
    assert len([n async for n in subscription_repository.unreported_aws_billing_entries()]) == 0
    await metering_repository.add(
        [
            create_metering_record(workspace_id=workspace.id, account_id="acc1", product_tier=ProductTier.Enterprise)
            for _ in range(4)
        ]
    )
    # before next charge: no billing entry is created
    await billing_job.create_overdue_billing_entries(before_next_charge, 16)
    assert len([n async for n in subscription_repository.unreported_aws_billing_entries()]) == 0
    # after next charge: one billing entry is created
    await billing_job.create_overdue_billing_entries(after_next_charge, 16)
    assert len([n async for n in subscription_repository.unreported_aws_billing_entries()]) == 1


async def test_report_no_usage(
    aws_marketplace_subscription: AwsMarketplaceSubscription,
    billing_job: BillingJob,
    boto_answers: Dict[str, Any],
    boto_requests: List[Tuple[str, Any]],
    workspace_repository: WorkspaceRepository,
    workspace: Workspace,
    user: User,
) -> None:
    # BatchMeterUsage request is successful
    boto_answers["BatchMeterUsage"] = {
        "Results": [{"MeteringRecordId": "123", "Status": "Success"}],
        "UnprocessedRecords": [],
    }
    # define a paid tier: otherwise nothing will be reported to AWS
    await workspace_repository.update_subscription(workspace.id, aws_marketplace_subscription.id)
    await workspace_repository.update_product_tier(workspace.id, ProductTier.Business)
    assert aws_marketplace_subscription.next_charge_timestamp
    before_next_charge = aws_marketplace_subscription.next_charge_timestamp - timedelta(days=1)
    after_next_charge = aws_marketplace_subscription.next_charge_timestamp + timedelta(days=1)
    # there is no subscription with no usage after next charge
    await billing_job.report_no_usage_for_active_aws_marketplace_subscriptions(after_next_charge, 16)
    assert len(boto_requests) == 0
    # there is one subscription that will be charged later
    await billing_job.report_no_usage_for_active_aws_marketplace_subscriptions(before_next_charge, 16)
    assert len(boto_requests) == 1
    assert boto_requests[0][0] == "BatchMeterUsage"
    # subscription is reported with no usage
    assert len(boto_requests[0][1]["UsageRecords"]) == 1
    first = boto_requests[0][1]["UsageRecords"][0]
    assert first["Quantity"] == 0
    assert first["CustomerIdentifier"] == aws_marketplace_subscription.customer_identifier
