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
from typing import ClassVar, TypeVar

from attrs import frozen
from fixcloudutils.types import Json

from fixbackend.domain_events.converter import converter
from fixbackend.ids import WorkspaceId, UserId

T = TypeVar("T")


@frozen
class AnalyticsEvent(ABC):
    kind: ClassVar[str]
    # The user that triggered the event. This id will NOT be sent to Google Analytics.
    user_id: UserId

    def to_json(self) -> Json:
        return converter.unstructure(self)  # type: ignore


@frozen
class AEUserRegistered(AnalyticsEvent):
    kind: ClassVar[str] = "fix_user_registered"
    workspace_id: WorkspaceId


@frozen
class AEAwsAccountDiscovered(AnalyticsEvent):
    kind: ClassVar[str] = "fix_aws_account_discovered"
    workspace_id: WorkspaceId


@frozen
class AEAwsAccountConfigured(AnalyticsEvent):
    kind: ClassVar[str] = "fix_aws_account_configured"
    workspace_id: WorkspaceId


@frozen
class AEAwsAccountDeleted(AnalyticsEvent):
    kind: ClassVar[str] = "fix_aws_account_deleted"
    workspace_id: WorkspaceId


@frozen
class AEAwsAccountDegraded(AnalyticsEvent):
    kind: ClassVar[str] = "fix_aws_account_degraded"
    workspace_id: WorkspaceId
    error: str


@frozen
class AEWorkspaceCreated(AnalyticsEvent):
    kind: ClassVar[str] = "fix_workspace_created"
    workspace_id: WorkspaceId


@frozen
class AEInvitationAccepted(AnalyticsEvent):
    kind: ClassVar[str] = "fix_workspace_invitation_accepted"
    workspace_id: WorkspaceId


@frozen
class AEUserJoinedWorkspace(AnalyticsEvent):
    kind: ClassVar[str] = "fix_user_joined_workspace"
    workspace_id: WorkspaceId


@frozen
class AESecurityTierUpdated(AnalyticsEvent):
    kind: ClassVar[str] = "fix_security_tier_updated"
    workspace_id: WorkspaceId
    security_tier: str
