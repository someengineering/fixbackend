from fixbackend.subscription.billing import BillingService
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.subscription.subscription_repository import SubscriptionRepository


async def test_billing_service(
    subscription_repository: SubscriptionRepository,
    subscription: AwsMarketplaceSubscription,
    billing_service: BillingService,
) -> None:
    assert len([n async for n in subscription_repository.unreported_billing_entries()]) == 0
    await billing_service.create_overdue_billing_entries()
    assert len([n async for n in subscription_repository.unreported_billing_entries()]) == 1
