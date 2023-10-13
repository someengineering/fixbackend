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


from typing import ClassVar, List
from attrs import frozen
from abc import ABC, abstractmethod
from fixbackend.ids import UserId, WorkspaceId, CloudAccountId
from fixcloudutils.types import Json

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
    cloud_id: str
    aws_account_id: str

    def to_json(self) -> Json:
        return converter.unstructure(self)  # type: ignore

    @staticmethod
    def from_json(json: Json) -> "AwsAccountDiscovered":
        return converter.structure(json, AwsAccountDiscovered)


@frozen
class TenantAccountsCollected(Event):
    kind: ClassVar[str] = "tenant_accounts_collected"

    tenant_id: WorkspaceId
    cloud_account_ids: List[CloudAccountId]

    def to_json(self) -> Json:
        return converter.unstructure(self)  # type: ignore

    @staticmethod
    def from_json(json: Json) -> "TenantAccountsCollected":
        return converter.structure(json, TenantAccountsCollected)
