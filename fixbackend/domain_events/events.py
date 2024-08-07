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


from abc import ABC
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Dict, Optional, TypeVar, Type, List, Literal

from attr import frozen, field
from fixcloudutils.types import Json
from fixcloudutils.util import utc, uuid_str

from fixbackend.domain_events.converter import converter
from fixbackend.ids import (
    SubscriptionId,
    UserId,
    WorkspaceId,
    FixCloudAccountId,
    CloudAccountId,
    CloudName,
    UserCloudAccountName,
    TaskId,
    BenchmarkName,
    ReportSeverity,
    NotificationProvider,
    ProductTier,
)

T = TypeVar("T")


@frozen(kw_only=True)
class Event(ABC):
    kind: ClassVar[str]
    id: str = field(factory=uuid_str)
    created_at: datetime = field(factory=utc)

    def to_json(self) -> Json:
        return converter.unstructure(self)  # type: ignore

    @classmethod
    def from_json(cls: Type[T], json: Json) -> T:
        return converter.structure(json, cls)


@frozen
class UserRegistered(Event):
    kind: ClassVar[str] = "user_registered"

    user_id: UserId
    email: str
    tenant_id: WorkspaceId


@frozen
class UserLoggedIn(Event):
    kind: ClassVar[str] = "user_logged_in"

    user_id: UserId
    email: str


@frozen
class CloudAccountDiscovered(Event):
    """
    This event is emitted when a cloud account callback is hit.
    """

    kind: ClassVar[str] = "cloud_account_discovered"

    cloud: CloudName
    cloud_account_id: FixCloudAccountId
    tenant_id: WorkspaceId
    account_id: CloudAccountId


@frozen
class CloudAccountConfigured(Event):
    """
    This event is emitted when a cloud account is ready to be collected.
    """

    kind: ClassVar[str] = "cloud_account_configured"

    cloud: CloudName
    cloud_account_id: FixCloudAccountId
    tenant_id: WorkspaceId
    account_id: CloudAccountId


@frozen
class CloudAccountDeleted(Event):
    kind: ClassVar[str] = "cloud_account_deleted"

    cloud: CloudName
    user_id: UserId
    cloud_account_id: FixCloudAccountId
    tenant_id: WorkspaceId
    account_id: CloudAccountId


class DegradationReason(StrEnum):
    stack_deleted = "stack_deleted"
    other = "other"


@frozen
class CloudAccountDegraded(Event):
    """
    This event is emitted when a cloud account is not collectable anymore.
    """

    kind: ClassVar[str] = "aws_account_degraded"

    cloud: CloudName
    cloud_account_id: FixCloudAccountId
    tenant_id: WorkspaceId
    account_id: CloudAccountId
    account_name: Optional[str]
    error: str
    reason: Optional[DegradationReason]


@frozen
class CloudAccountNameChanged(Event):
    """
    This event is emitted when the name of an account has changed
    """

    kind: ClassVar[str] = "cloud_account_name_changed"

    cloud_account_id: FixCloudAccountId
    tenant_id: WorkspaceId
    cloud: CloudName
    account_id: CloudAccountId
    state: str
    name: Optional[UserCloudAccountName]
    final_name: Optional[str]


@frozen
class CloudAccountActiveToggled(Event):
    """
    This event is emitted when a cloud account is marked active/non-active.
    """

    kind: ClassVar[str] = "cloud_account_active_toggled"

    tenant_id: WorkspaceId
    cloud_account_id: FixCloudAccountId
    account_id: CloudAccountId
    enabled: bool


@frozen
class CloudAccountScanToggled(Event):
    """
    This event is emitted when a cloud account is maarked active/non-active for scanning vulnerabilities.
    """

    kind: ClassVar[str] = "cloud_account_scan_toggled"

    tenant_id: WorkspaceId
    cloud_account_id: FixCloudAccountId
    account_id: CloudAccountId
    enabled: bool
    scan: bool


@frozen
class CloudAccountCollectInfo:
    account_id: CloudAccountId
    scanned_resources: int
    duration_seconds: int
    started_at: datetime
    task_id: Optional[TaskId]
    errors: List[str]


@frozen
class TenantAccountsCollected(Event):
    kind: ClassVar[str] = "tenant_accounts_collected"

    tenant_id: WorkspaceId
    cloud_accounts: Dict[FixCloudAccountId, CloudAccountCollectInfo]
    cloud_accounts_failed: Dict[FixCloudAccountId, CloudAccountCollectInfo]
    next_run: Optional[datetime]

    # delete me after deploying this change to production
    @classmethod
    def from_json(cls: Type["TenantAccountsCollected"], json: Json) -> "TenantAccountsCollected":

        if not json.get("cloud_accounts_failed"):
            json["cloud_accounts_failed"] = {}

        for cloud_account in json["cloud_accounts"].values():
            if not cloud_account.get("errors"):
                cloud_account["errors"] = []

        return converter.structure(json, cls)


@frozen
class TenantAccountsCollectFailed(Event):
    kind: ClassVar[str] = "tenant_accounts_collect_failed"

    tenant_id: WorkspaceId
    cloud_accounts: Dict[FixCloudAccountId, CloudAccountCollectInfo]
    next_run: Optional[datetime]


@frozen
class WorkspaceCreated(Event):
    kind: ClassVar[str] = "workspace_created"

    workspace_id: WorkspaceId
    name: str
    slug: str
    user_id: UserId


@frozen
class InvitationAccepted(Event):
    kind: ClassVar[str] = "workspace_invitation_accepted"

    workspace_id: WorkspaceId
    user_id: Optional[UserId]
    user_email: str


@frozen
class UserJoinedWorkspace(Event):
    kind: ClassVar[str] = "user_joined_workspace"

    workspace_id: WorkspaceId
    user_id: UserId


@frozen
class ProductTierChanged(Event):
    kind: ClassVar[str] = "product_tier_changed"

    workspace_id: WorkspaceId
    user_id: UserId
    product_tier: ProductTier
    is_paid_tier: bool
    is_higher_tier: bool
    previous_tier: ProductTier


@frozen
class SubscriptionCreated(Event):
    """
    This event is emitted when a user gets an AWS Marketplace subscription.
    """

    kind: ClassVar[str] = "subscription_created"
    workspace_id: Optional[WorkspaceId]
    user_id: UserId
    subscription_id: SubscriptionId
    method: Literal["aws_marketplace", "stripe"]


@frozen
class SubscriptionCancelled(Event):
    """
    This event is emitted when a user cancels an AWS Marketplace subscription.
    """

    kind: ClassVar[str] = "subscription_cancelled"

    subscription_id: SubscriptionId
    method: Literal["aws_marketplace", "stripe"]


@frozen
class FailingBenchmarkChecksAlertSend(Event):
    """
    This event is emitted when a user gets notified about failing benchmark checks.
    """

    kind: ClassVar[str] = "failing_benchmark_checks_alert_send"

    workspace_id: WorkspaceId
    benchmark: BenchmarkName
    severity: ReportSeverity
    failed_checks_count_total: int
    channels: List[NotificationProvider]


@frozen
class BillingEntryCreated(Event):
    """
    This event is emitted when a billing entry for a workspace is created.
    """

    kind: ClassVar[str] = "billing_entry_created"

    tenant_id: WorkspaceId
    subscription_id: SubscriptionId
    product_tier: str
    usage: int


@frozen
class AlertNotificationSetupUpdated(Event):
    kind: ClassVar[str] = "alert_notification_setup_updated"

    tenant_id: WorkspaceId
    user_id: UserId
    provider: NotificationProvider
