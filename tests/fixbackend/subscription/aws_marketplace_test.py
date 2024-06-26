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
from datetime import datetime, timezone
from functools import partial
from typing import Dict, Any, List, Tuple

from attr import evolve

from fixbackend.auth.models import User
from fixbackend.ids import ProductTier
from fixbackend.metering.metering_repository import MeteringRepository
from fixbackend.subscription.aws_marketplace import AwsMarketplaceHandler
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository
from tests.fixbackend.metering.metering_repository_test import create_metering_record


async def test_handle_subscription(
    aws_marketplace_handler: AwsMarketplaceHandler, user: User, boto_answers: Dict[str, Any]
) -> None:
    boto_answers["ResolveCustomer"] = {"CustomerAWSAccountId": "1", "CustomerIdentifier": "2", "ProductCode": "3"}
    result, workspace_added = await aws_marketplace_handler.subscribed(user, "123")
    assert result is not None
    assert result.customer_aws_account_id == "1"
    assert result.customer_identifier == "2"
    assert result.product_code == "3"
    assert result.user_id == user.id
    assert workspace_added is False  # user does not have any workspaces yet
    # subscribe again: will not create a new subscription
    result2, workspace_added = await aws_marketplace_handler.subscribed(user, "123")
    assert result2 is not None
    assert workspace_added is False
    assert result == evolve(result2, last_charge_timestamp=result.last_charge_timestamp)


async def test_create_billing_entry(
    aws_marketplace_handler: AwsMarketplaceHandler,
    user: User,
    workspace: Workspace,
    aws_marketplace_subscription: AwsMarketplaceSubscription,
    boto_requests: List[Tuple[str, Any]],
    boto_answers: Dict[str, Any],
    metering_repository: MeteringRepository,
    subscription_repository: SubscriptionRepository,
    workspace_repository: WorkspaceRepository,
) -> None:
    now = datetime(2020, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
    boto_answers["BatchMeterUsage"] = {
        "Results": [{"MeteringRecordId": "123", "Status": "Success"}],
        "UnprocessedRecords": [],
    }
    await workspace_repository.update_subscription(workspace.id, aws_marketplace_subscription.id)
    # factories to create metering records
    mr1free = partial(
        create_metering_record, workspace_id=workspace.id, account_id="acc1", product_tier=ProductTier.Free
    )
    mr1enterprise = partial(
        create_metering_record, workspace_id=workspace.id, account_id="acc1", product_tier=ProductTier.Enterprise
    )

    mr2 = partial(create_metering_record, workspace_id=workspace.id, account_id="acc2", product_tier=ProductTier.Free)
    # create 3 metering records for acc1 and acc2, each with more than 100 resource collected
    await metering_repository.add(
        [mr1free(), mr1free(), mr1free(), mr1enterprise(), mr1enterprise(), mr1enterprise(), mr2(), mr2(), mr2()]
    )
    # create billing entry
    billing = await aws_marketplace_handler.billing_entry_service.create_billing_entry(
        aws_marketplace_subscription, now=now
    )
    assert billing is not None
    assert billing.period_start == datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert billing.period_end == datetime(2020, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert billing.nr_of_accounts_charged == 25
    assert billing.reported is False
    assert billing.tier == ProductTier.Enterprise
    # report all unreported billing entries to AWS
    assert len([i async for i in subscription_repository.unreported_aws_billing_entries()]) == 1
    assert len(boto_requests) == 0
    await aws_marketplace_handler.report_unreported_usages()
    assert len(boto_requests) == 1
    boto_requests[0][1]["UsageRecords"][0].pop("Timestamp")
    assert boto_requests[0][1] == {
        "ProductCode": "foo",
        "UsageRecords": [{"CustomerIdentifier": "123", "Dimension": "EnterpriseAccount", "Quantity": 25}],
    }
    # make sure there is no unreported billing entry anymore
    assert len([i async for i in subscription_repository.unreported_aws_billing_entries()]) == 0


async def test_create_daily_billing_entry(
    aws_marketplace_handler: AwsMarketplaceHandler,
    user: User,
    workspace: Workspace,
    aws_marketplace_subscription: AwsMarketplaceSubscription,
    boto_requests: List[Tuple[str, Any]],
    boto_answers: Dict[str, Any],
    metering_repository: MeteringRepository,
    subscription_repository: SubscriptionRepository,
    workspace_repository: WorkspaceRepository,
) -> None:
    # set billing period to daily
    aws_marketplace_handler.billing_entry_service.billing_period = "day"
    await workspace_repository.update_subscription(workspace.id, aws_marketplace_subscription.id)

    now = datetime(2020, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
    boto_answers["BatchMeterUsage"] = {
        "Results": [{"MeteringRecordId": "123", "Status": "Success"}],
        "UnprocessedRecords": [],
    }
    # factories to create metering records
    mr1free = partial(
        create_metering_record, workspace_id=workspace.id, account_id="acc1", product_tier=ProductTier.Free
    )
    mr1high = partial(
        create_metering_record, workspace_id=workspace.id, account_id="acc1", product_tier=ProductTier.Enterprise
    )

    mr2 = partial(create_metering_record, workspace_id=workspace.id, account_id="acc2", product_tier=ProductTier.Free)
    # create 3 metering records for acc1 and acc2, each with more than 100 resource collected
    await metering_repository.add(
        [mr1free(), mr1free(), mr1free(), mr1high(), mr1high(), mr1high(), mr2(), mr2(), mr2()]
    )
    # create billing entry
    billing = await aws_marketplace_handler.billing_entry_service.create_billing_entry(
        aws_marketplace_subscription, now=now
    )
    assert billing is not None
    assert billing.period_start == datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert billing.period_end == datetime(2020, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
    assert billing.nr_of_accounts_charged == 25
    assert billing.reported is False
    assert billing.tier == ProductTier.Enterprise
    # report all unreported billing entries to AWS
    assert len([i async for i in subscription_repository.unreported_aws_billing_entries()]) == 1
    assert len(boto_requests) == 0
    await aws_marketplace_handler.report_unreported_usages()
    assert len(boto_requests) == 1
    boto_requests[0][1]["UsageRecords"][0].pop("Timestamp")
    assert boto_requests[0][1] == {
        "ProductCode": "foo",
        "UsageRecords": [{"CustomerIdentifier": "123", "Dimension": "EnterpriseAccount", "Quantity": 25}],
    }
    # make sure there is no unreported billing entry anymore
    assert len([i async for i in subscription_repository.unreported_aws_billing_entries()]) == 0


async def test_create_free_tier_billing_entry(
    aws_marketplace_handler: AwsMarketplaceHandler,
    user: User,
    workspace: Workspace,
    aws_marketplace_subscription: AwsMarketplaceSubscription,
    boto_requests: List[Tuple[str, Any]],
    boto_answers: Dict[str, Any],
    metering_repository: MeteringRepository,
    subscription_repository: SubscriptionRepository,
) -> None:
    now = datetime(2020, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
    boto_answers["BatchMeterUsage"] = {
        "Results": [{"MeteringRecordId": "123", "Status": "Success"}],
        "UnprocessedRecords": [],
    }
    # factories to create metering records
    mr1free = partial(
        create_metering_record, workspace_id=workspace.id, account_id="acc1", product_tier=ProductTier.Free
    )

    mrTrial = partial(
        create_metering_record, workspace_id=workspace.id, account_id="acc3", product_tier=ProductTier.Trial
    )

    mr2 = partial(create_metering_record, workspace_id=workspace.id, account_id="acc2", product_tier=ProductTier.Free)
    # create 3 metering records for acc1 and acc2, all with free tiers
    await metering_repository.add([mr1free(), mr1free(), mr1free(), mrTrial(), mrTrial(), mr2(), mr2(), mr2()])
    # billing entry is not created for free tier accounts because we have a job that reports dummy zero usage for such cases
    billing = await aws_marketplace_handler.billing_entry_service.create_billing_entry(
        aws_marketplace_subscription, now=now
    )
    assert billing is None
