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
from typing import List, Optional

from fixbackend.auth.models import User
from fixbackend.cloud_accounts.models import CloudAccount
from fixbackend.ids import (
    AwsRoleName,
    CloudAccountId,
    CloudAccountName,
    ExternalId,
    FixCloudAccountId,
    UserCloudAccountName,
    WorkspaceId,
)


class WrongExternalId(Exception):
    pass


class CloudAccountService(ABC):
    @abstractmethod
    async def create_aws_account(
        self,
        *,
        workspace_id: WorkspaceId,
        account_id: CloudAccountId,
        role_name: Optional[AwsRoleName],
        external_id: ExternalId,
        account_name: Optional[CloudAccountName],
    ) -> CloudAccount:
        """Create a cloud account."""
        raise NotImplementedError

    @abstractmethod
    async def delete_cloud_account(
        self, user: User, cloud_account_id: FixCloudAccountId, workspace_id: WorkspaceId
    ) -> None:
        """Delete a cloud account."""
        raise NotImplementedError

    @abstractmethod
    async def get_cloud_account(self, cloud_account_id: FixCloudAccountId, workspace_id: WorkspaceId) -> CloudAccount:
        """Get a cloud account."""
        raise NotImplementedError

    @abstractmethod
    async def list_accounts(self, workspace_id: WorkspaceId) -> List[CloudAccount]:
        """List all cloud accounts"""
        raise NotImplementedError

    @abstractmethod
    async def update_cloud_account_name(
        self,
        workspace_id: WorkspaceId,
        cloud_account_id: FixCloudAccountId,
        name: Optional[UserCloudAccountName],
    ) -> CloudAccount:
        """Update a cloud account."""
        raise NotImplementedError

    @abstractmethod
    async def enable_cloud_account(
        self,
        workspace_id: WorkspaceId,
        cloud_account_id: FixCloudAccountId,
    ) -> CloudAccount:
        """Enable a cloud account."""
        raise NotImplementedError

    @abstractmethod
    async def disable_cloud_account(
        self,
        workspace_id: WorkspaceId,
        cloud_account_id: FixCloudAccountId,
    ) -> CloudAccount:
        """Disable a cloud account."""
        raise NotImplementedError
