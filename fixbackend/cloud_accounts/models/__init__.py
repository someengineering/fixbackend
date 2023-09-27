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
from typing import Union

from attrs import frozen

from fixbackend.ids import TenantId, CloudAccountId


@frozen
class AwsCloudAccess:
    account_id: str
    role_name: str


@frozen
class GcpCloudAccess:
    project_id: str


CloudAccess = Union[AwsCloudAccess, GcpCloudAccess]


@frozen
class CloudAccount:
    id: CloudAccountId
    tenant_id: TenantId
    access: CloudAccess
