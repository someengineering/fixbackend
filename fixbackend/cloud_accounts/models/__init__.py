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
from typing import Dict, Union, Optional

from attrs import frozen

from fixbackend.ids import FixCloudAccountId, ExternalId, WorkspaceId, CloudAccountId


@frozen
class AwsCloudAccess:
    account_id: CloudAccountId
    external_id: ExternalId
    role_name: str


@frozen
class GcpCloudAccess:
    project_id: CloudAccountId


CloudAccess = Union[AwsCloudAccess, GcpCloudAccess]


@frozen
class CloudAccount:
    id: FixCloudAccountId
    workspace_id: WorkspaceId
    access: CloudAccess


@frozen
class LastScanAccountInfo:
    account_id: CloudAccountId
    duration_seconds: int
    resources_scanned: int


@frozen
class LastScanInfo:
    accounts: Dict[FixCloudAccountId, LastScanAccountInfo]
    next_scan: Optional[datetime]
