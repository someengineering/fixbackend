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
from typing import Optional

from fixbackend.cloud_accounts.models import CloudAccount, LastScanInfo

from fixbackend.ids import FixCloudAccountId, ExternalId, WorkspaceId, CloudAccountId


class WrongExternalId(Exception):
    pass


class CloudAccountService(ABC):
    @abstractmethod
    async def create_aws_account(
        self, workspace_id: WorkspaceId, account_id: CloudAccountId, role_name: str, external_id: ExternalId
    ) -> CloudAccount:
        """Create a cloud account."""
        raise NotImplementedError

    @abstractmethod
    async def delete_cloud_account(self, cloud_account_id: FixCloudAccountId, workspace_id: WorkspaceId) -> None:
        """Delete a cloud account."""
        raise NotImplementedError

    @abstractmethod
    async def last_scan(self, workspace_id: WorkspaceId) -> Optional[LastScanInfo]:
        """Get the last scan statistics for workspace."""
        raise NotImplementedError
