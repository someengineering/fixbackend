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


from typing import ClassVar, Dict, Optional
from attrs import frozen
from abc import ABC, abstractmethod
from fixbackend.ids import UserId, WorkspaceId, CloudAccountId
from fixcloudutils.types import Json
from datetime import datetime

from fixbackend.domain_events.converter import converter


@frozen
class Event(ABC):
    kind: ClassVar[str]

    @abstractmethod
    def to_json(self) -> Json:
        ...

    @staticmethod
    @abstractmethod
    def from_json(json: Json) -> "Event":
        ...


@frozen
class UserRegistered(Event):
    kind: ClassVar[str] = "user_registered"

    user_id: UserId
    email: str
    tenant_id: WorkspaceId

    def to_json(self) -> Json:
        return converter.unstructure(self)  # type: ignore

    @staticmethod
    def from_json(json: Json) -> "UserRegistered":
        return converter.structure(json, UserRegistered)


@frozen
class AwsAccountDiscovered(Event):
    kind: ClassVar[str] = "aws_account_discovered"

    cloud_account_id: CloudAccountId
    tenant_id: WorkspaceId
    aws_account_id: str

    def to_json(self) -> Json:
        return converter.unstructure(self)  # type: ignore

    @staticmethod
    def from_json(json: Json) -> "AwsAccountDiscovered":
        return converter.structure(json, AwsAccountDiscovered)


@frozen
class AwsAccountDeleted(Event):
    kind: ClassVar[str] = "aws_account_deleted"

    cloud_account_id: CloudAccountId
    tenant_id: WorkspaceId
    aws_account_id: str

    def to_json(self) -> Json:
        return converter.unstructure(self)  # type: ignore

    @staticmethod
    def from_json(json: Json) -> "AwsAccountDeleted":
        return converter.structure(json, AwsAccountDeleted)


@frozen
class CloudAccountCollectInfo:
    aws_account_id: str
    scanned_resources: int
    duration_seconds: int


@frozen
class TenantAccountsCollected(Event):
    kind: ClassVar[str] = "tenant_accounts_collected"

    tenant_id: WorkspaceId
    cloud_accounts: Dict[CloudAccountId, CloudAccountCollectInfo]
    next_run: Optional[datetime]

    def to_json(self) -> Json:
        return converter.unstructure(self)  # type: ignore

    @staticmethod
    def from_json(json: Json) -> "TenantAccountsCollected":
        return converter.structure(json, TenantAccountsCollected)


@frozen
class WorkspaceCreated(Event):
    kind: ClassVar[str] = "workspace_created"

    workspace_id: WorkspaceId

    def to_json(self) -> Json:
        return converter.unstructure(self)  # type: ignore

    @staticmethod
    def from_json(json: Json) -> "WorkspaceCreated":
        return converter.structure(json, WorkspaceCreated)
