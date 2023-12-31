from typing import NewType, Any
from uuid import UUID
from enum import Enum
from functools import total_ordering

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
CloudAccountName = NewType("CloudAccountName", str)
CloudAccountAlias = NewType("CloudAccountAlias", str)
UserCloudAccountName = NewType("UserCloudAccountName", str)

CloudName = NewType("CloudName", str)


class CloudNames:
    AWS: CloudName = CloudName("aws")
    GCP: CloudName = CloudName("gcp")


@total_ordering
class SecurityTier(str, Enum):
    # do not change the values of these enums, or things will break
    Free = "FreeAccount"
    Foundational = "FoundationalSecurityAccount"
    HighSecurity = "HighSecurityAccount"

    def __lt__(self, other: Any) -> bool:
        if self.__class__ is other.__class__:
            return __security_tier_order(self) < __security_tier_order(other)
        return NotImplemented


def __security_tier_order(tier: "SecurityTier") -> int:
    match tier:
        case SecurityTier.Free:
            return 0
        case SecurityTier.Foundational:
            return 1
        case SecurityTier.HighSecurity:
            return 2
