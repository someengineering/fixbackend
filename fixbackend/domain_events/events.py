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


from typing import ClassVar
from attrs import frozen
from abc import ABC
from fixbackend.ids import UserId, WorkspaceId, CloudAccountId


@frozen
class Event(ABC):
    kind: ClassVar[str]


@frozen
class UserRegistered(Event):
    kind: ClassVar[str] = "user_registered"

    user_id: UserId
    email: str
    tenant_id: WorkspaceId


@frozen
class AwsAccountDiscovered(Event):
    kind: ClassVar[str] = "aws_account_discovered"

    cloud_account_id: CloudAccountId
    tenant_id: WorkspaceId
    cloud_id: str
    aws_account_id: str
