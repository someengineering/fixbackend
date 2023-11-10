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

from datetime import datetime
from typing import ClassVar, Dict, Optional
from abc import ABC

from attrs import frozen

from fixbackend.ids import (
    CloudAccountId,
    ExternalId,
    FixCloudAccountId,
    WorkspaceId,
    AwsRoleName,
    CloudAccountName,
    CloudAccountAlias,
    UserCloudAccountName,
    CloudName,
    CloudNames,
)


@frozen
class CloudAccess(ABC):
    cloud: ClassVar[CloudName]


@frozen
class AwsCloudAccess(CloudAccess):
    cloud: ClassVar[CloudName] = CloudNames.AWS

    external_id: ExternalId
    role_name: AwsRoleName


@frozen
class GcpCloudAccess(CloudAccess):
    cloud: ClassVar[CloudName] = CloudNames.GCP


@frozen
class CloudAccountState(ABC):
    state_name: ClassVar[str]


class CloudAccountStates:
    """
    @startuml
    hide empty description
    [*] --> Discovered: CF Stack
    Discovered --> Configured: can assume role
    Discovered --> Degraded: can not assume the role
    Degraded --> Discovered: Redeploy CF Stack
    Configured -[dotted]-> Detected: find other accounts in org
    Configured --> Degraded: collection failed
    Degraded --> Configured: backend test
    @enduml
    """

    @frozen
    class Detected(CloudAccountState):
        """
        We know that the account exists, but we lack necessary data to configure it.
        """

        state_name: ClassVar[str] = "detected"

    @frozen
    class Discovered(CloudAccountState):
        """
        We know how to configure the account, but we haven't done so yet.
        """

        state_name: ClassVar[str] = "discovered"
        access: CloudAccess

    @frozen
    class Configured(CloudAccountState):
        """
        We have configured the account and it is ready for collection.
        """

        state_name: ClassVar[str] = "configured"
        access: CloudAccess
        enabled: bool  # is enabled for collection

    @frozen
    class Degraded(CloudAccountState):
        """
        Resource collection is not possible. We will still try to probe this account to come back to configured.
        """

        state_name: ClassVar[str] = "degraded"
        access: CloudAccess
        error: str


@frozen(kw_only=True)
class CloudAccount:
    id: FixCloudAccountId
    account_id: CloudAccountId
    workspace_id: WorkspaceId
    cloud: CloudName
    state: CloudAccountState
    account_name: Optional[CloudAccountName]
    account_alias: Optional[CloudAccountAlias]
    user_account_name: Optional[UserCloudAccountName]
    privileged: bool  # can do administrative tasks


@frozen
class LastScanAccountInfo:
    account_id: CloudAccountId
    duration_seconds: int
    resources_scanned: int
    started_at: datetime


@frozen
class LastScanInfo:
    accounts: Dict[FixCloudAccountId, LastScanAccountInfo]
    next_scan: Optional[datetime]
