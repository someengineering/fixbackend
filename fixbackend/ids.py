from typing import NewType
from uuid import UUID

WorkspaceId = NewType("WorkspaceId", UUID)
InvitationId = NewType("InvitationId", UUID)
UserId = NewType("UserId", UUID)
FixCloudAccountId = NewType("FixCloudAccountId", UUID)  # fix-internal cloud account id
CloudAccountId = NewType("CloudAccountId", str)  # cloud account id, e.g. AWS account id, GCP project id, etc.
ExternalId = NewType("ExternalId", UUID)
SubscriptionId = NewType("SubscriptionId", UUID)
BillingId = NewType("BillingId", UUID)
