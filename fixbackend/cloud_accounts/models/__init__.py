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

from abc import ABC, abstractmethod
from datetime import datetime
from typing import ClassVar, Dict, Optional

from attrs import frozen

from fixbackend.ids import CloudAccountId, ExternalId, FixCloudAccountId, WorkspaceId


@frozen
class CloudAccess(ABC):
    cloud: ClassVar[str]

    @abstractmethod
    def account_id(self) -> CloudAccountId:
        raise NotImplementedError


@frozen
class AwsCloudAccess(CloudAccess):
    cloud: ClassVar[str] = "aws"

    aws_account_id: CloudAccountId
    external_id: ExternalId
    role_name: str

    def account_id(self) -> CloudAccountId:
        return self.aws_account_id


@frozen
class GcpCloudAccess(CloudAccess):
    cloud: ClassVar[str] = "gcp"

    project_id: CloudAccountId

    def account_id(self) -> CloudAccountId:
        return self.project_id


@frozen
class CloudAccount:
    id: FixCloudAccountId
    workspace_id: WorkspaceId
    name: Optional[str]
    access: CloudAccess


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
