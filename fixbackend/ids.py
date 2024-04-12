from collections import defaultdict
from enum import StrEnum
from typing import NewType, Any, Literal
from uuid import UUID

WorkspaceId = NewType("WorkspaceId", UUID)
InvitationId = NewType("InvitationId", UUID)
UserId = NewType("UserId", UUID)
FixCloudAccountId = NewType("FixCloudAccountId", UUID)  # fix-internal cloud account id
CloudAccountId = NewType("CloudAccountId", str)  # cloud account id, e.g. AWS account id, GCP project id, etc.
ExternalId = NewType("ExternalId", UUID)
SubscriptionId = NewType("SubscriptionId", UUID)
BillingId = NewType("BillingId", UUID)
NodeId = NewType("NodeId", str)
AwsRoleName = NewType("AwsRoleName", str)
AwsARN = NewType("AwsARN", str)
CloudName = NewType("CloudName", str)
CloudAccountName = NewType("CloudAccountName", str)
CloudAccountAlias = NewType("CloudAccountAlias", str)
UserCloudAccountName = NewType("UserCloudAccountName", str)
TaskId = NewType("TaskId", str)
BenchmarkName = NewType("BenchmarkName", str)
UserRoleId = NewType("UserRoleId", UUID)
Email = NewType("Email", str)
StripeCustomerId = NewType("StripeCustomerId", str)


class NotificationProvider(StrEnum):
    email = "email"
    slack = "slack"
    discord = "discord"
    pagerduty = "pagerduty"
    teams = "teams"
    opsgenie = "opsgenie"


BillingPeriod = Literal["month", "day"]
ReportSeverity = Literal["info", "low", "medium", "high", "critical"]


class CloudNames:
    AWS: CloudName = CloudName("aws")
    GCP: CloudName = CloudName("gcp")


class ProductTier(StrEnum):
    # do not change the values of these enums, or things will break
    Trial = "Trial"
    Free = "Free"
    # Paid Tiers
    Plus = "Plus"
    Business = "Business"
    Enterprise = "Enterprise"

    @property
    def paid(self) -> bool:
        not_free = self != ProductTier.Free
        not_trial = self != ProductTier.Trial
        return not_free and not_trial

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, ProductTier):
            return _product_tier_order[self] < _product_tier_order[other]
        return NotImplemented

    def __le__(self, other: Any) -> bool:
        if isinstance(other, ProductTier):
            return _product_tier_order[self] <= _product_tier_order[other]
        return NotImplemented

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, ProductTier):
            return _product_tier_order[self] > _product_tier_order[other]
        return NotImplemented

    def __ge__(self, other: Any) -> bool:
        if isinstance(other, ProductTier):
            return _product_tier_order[self] >= _product_tier_order[other]
        return NotImplemented

    @staticmethod
    def from_str(value: str) -> "ProductTier":
        match value:
            # for backwards compatibility
            case "FreeAccount":
                return ProductTier.Free
            case "EnterpriseAccount":
                return ProductTier.Enterprise
            case _:
                return ProductTier(value)


_product_tier_order = defaultdict(
    lambda: 0,
    {
        ProductTier.Trial: 0,
        ProductTier.Free: 1,
        ProductTier.Plus: 2,
        ProductTier.Business: 3,
        ProductTier.Enterprise: 4,
    },
)
