from fixbackend.metering.metering_repository import MeteringRepository
from fixbackend.subscription.billing import BillingService
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.workspaces.models import Workspace
from tests.fixbackend.metering.metering_repository_test import create_metering_record


async def test_billing_service(
    subscription_repository: SubscriptionRepository,
    subscription: AwsMarketplaceSubscription,
    billing_service: BillingService,
    metering_repository: MeteringRepository,
    workspace: Workspace,
) -> None:
    assert len([n async for n in subscription_repository.unreported_billing_entries()]) == 0
    await metering_repository.add(
        [create_metering_record(workspace_id=workspace.id, account_id="acc1") for a in range(4)]
    )
    await billing_service.create_overdue_billing_entries()
    assert len([n async for n in subscription_repository.unreported_billing_entries()]) == 1
