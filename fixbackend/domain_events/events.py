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
from typing import ClassVar, Dict, Optional, TypeVar, Type

from attrs import frozen
from fixcloudutils.types import Json

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
)

T = TypeVar("T")


class Event(ABC):
    kind: ClassVar[str]

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
class AwsAccountDiscovered(Event):
    """
    This event is emitted when the cloud account callback is hit.
    """

    kind: ClassVar[str] = "aws_account_discovered"

    cloud_account_id: FixCloudAccountId
    tenant_id: WorkspaceId
    aws_account_id: CloudAccountId


@frozen
class AwsAccountConfigured(Event):
    """
    This event is emitted when AWS account is ready to be collected.
    """

    kind: ClassVar[str] = "aws_account_configured"

    cloud_account_id: FixCloudAccountId
    tenant_id: WorkspaceId
    aws_account_id: CloudAccountId


@frozen
class AwsAccountDeleted(Event):
    kind: ClassVar[str] = "aws_account_deleted"

    user_id: UserId
    cloud_account_id: FixCloudAccountId
    tenant_id: WorkspaceId
    aws_account_id: CloudAccountId


@frozen
class AwsAccountDegraded(Event):
    """
    This event is emitted when AWS account is ready to be collected.
    """

    kind: ClassVar[str] = "aws_account_degraded"

    cloud_account_id: FixCloudAccountId
    tenant_id: WorkspaceId
    aws_account_id: CloudAccountId
    error: str


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
class CloudAccountCollectInfo:
    account_id: CloudAccountId
    scanned_resources: int
    duration_seconds: int
    started_at: datetime
    task_id: Optional[TaskId]


@frozen
class TenantAccountsCollected(Event):
    kind: ClassVar[str] = "tenant_accounts_collected"

    tenant_id: WorkspaceId
    cloud_accounts: Dict[FixCloudAccountId, CloudAccountCollectInfo]
    next_run: Optional[datetime]


@frozen
class WorkspaceCreated(Event):
    kind: ClassVar[str] = "workspace_created"

    workspace_id: WorkspaceId
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
class SecurityTierUpdated(Event):
    kind: ClassVar[str] = "security_tier_updated"

    workspace_id: WorkspaceId
    user_id: UserId
    security_tier: str


@frozen
class AwsMarketplaceSubscriptionCreated(Event):
    """
    This event is emitted when a user gets an AWS Marketplace subscription.
    """

    kind: ClassVar[str] = "aws_marketplace_subscription_created"

    workspace_id: Optional[WorkspaceId]
    user_id: UserId
    subscription_id: SubscriptionId
