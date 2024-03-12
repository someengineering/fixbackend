from collections import defaultdict
from datetime import timedelta
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


class NotificationProvider(StrEnum):
    email = "email"
    slack = "slack"
    discord = "discord"
    pagerduty = "pagerduty"
    teams = "teams"
    opsgenie = "opsgenie"


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
        return self != ProductTier.Free

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

    def can_add_seat(self, current_seats: int) -> bool:
        match self:
            case ProductTier.Trial:
                return current_seats < 1
            case ProductTier.Free:
                return current_seats < 1
            case ProductTier.Plus:
                return current_seats < 2
            case ProductTier.Business:
                return current_seats < 50
            case ProductTier.Enterprise:
                return True

    def scan_period(self) -> timedelta:
        match self:
            case ProductTier.Trial:
                return timedelta(hours=1)
            case ProductTier.Free:
                return timedelta(days=30)
            case ProductTier.Plus:
                return timedelta(days=1)
            case ProductTier.Business:
                return timedelta(hours=1)
            case ProductTier.Enterprise:
                return timedelta(hours=1)

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
