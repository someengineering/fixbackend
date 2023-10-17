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


import uuid
from abc import ABC, abstractmethod
from hmac import compare_digest
from typing import Annotated, Optional

from attrs import evolve
from fastapi import Depends
from fixcloudutils.redis.pub_sub import RedisPubSubPublisher

from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount
from fixbackend.cloud_accounts.repository import CloudAccountRepository, CloudAccountRepositoryDependency
from fixbackend.dependencies import FixDependency
from fixbackend.domain_events.dependencies import DomainEventPublisherDependency
from fixbackend.domain_events.events import AwsAccountDeleted, AwsAccountDiscovered
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.errors import Unauthorized
from fixbackend.ids import CloudAccountId, ExternalId, WorkspaceId
from fixbackend.workspaces.repository import WorkspaceRepository, WorkspaceRepositoryDependency


class WrongExternalId(Exception):
    pass


class CloudAccountService(ABC):
    @abstractmethod
    async def create_aws_account(
        self, workspace_id: WorkspaceId, account_id: str, role_name: str, external_id: ExternalId
    ) -> CloudAccount:
        """Create a cloud account."""
        raise NotImplementedError

    @abstractmethod
    async def delete_cloud_account(self, cloud_account_id: CloudAccountId, workspace_id: WorkspaceId) -> None:
        """Delete a cloud account."""
        raise NotImplementedError


class CloudAccountServiceImpl(CloudAccountService):
    def __init__(
        self,
        workspace_repository: WorkspaceRepository,
        cloud_account_repository: CloudAccountRepository,
        pubsub_publisher: RedisPubSubPublisher,
        domain_event_publisher: DomainEventPublisher,
    ) -> None:
        self.workspace_repository = workspace_repository
        self.cloud_account_repository = cloud_account_repository
        self.pubsub_publisher = pubsub_publisher
        self.domain_events = domain_event_publisher

    async def create_aws_account(
        self, workspace_id: WorkspaceId, account_id: str, role_name: str, external_id: ExternalId
    ) -> CloudAccount:
        """Create a cloud account."""

        organization = await self.workspace_repository.get_workspace(workspace_id)
        if organization is None:
            raise ValueError("Organization does not exist")
        if not compare_digest(str(organization.external_id), str(external_id)):
            raise WrongExternalId("External ids does not match")

        async def account_already_exists(workspace_id: WorkspaceId, account_id: str) -> Optional[CloudAccount]:
            accounts = await self.cloud_account_repository.list_by_workspace_id(workspace_id)
            maybe_account = next(
                iter(
                    [
                        account
                        for account in accounts
                        if isinstance(account.access, AwsCloudAccess) and account.access.account_id == account_id
                    ]
                ),
                None,
            )
            return maybe_account

        account = CloudAccount(
            id=CloudAccountId(uuid.uuid4()),
            workspace_id=workspace_id,
            access=AwsCloudAccess(account_id=account_id, external_id=external_id, role_name=role_name),
        )
        if existing := await account_already_exists(workspace_id, account_id):
            account = evolve(account, id=existing.id)
            result = await self.cloud_account_repository.update(existing.id, account)
        else:
            result = await self.cloud_account_repository.create(account)

        message = {
            "cloud_account_id": str(result.id),
            "workspace_id": str(result.workspace_id),
            "aws_account_id": account_id,
        }
        await self.pubsub_publisher.publish(
            kind="cloud_account_created", message=message, channel=f"tenant-events::{workspace_id}"
        )
        await self.domain_events.publish(
            AwsAccountDiscovered(cloud_account_id=result.id, tenant_id=workspace_id, aws_account_id=account_id)
        )
        return result

    async def delete_cloud_account(self, cloud_account_id: CloudAccountId, workspace_id: WorkspaceId) -> None:
        account = await self.cloud_account_repository.get(cloud_account_id)
        if account is None:
            return None  # account already deleted, do nothing
        if account.workspace_id != workspace_id:
            raise Unauthorized("Deletion of cloud accounts is only allowed by the owning organization.")

        await self.cloud_account_repository.delete(cloud_account_id)
        match account.access:
            case AwsCloudAccess(account_id, _, _):
                await self.domain_events.publish(AwsAccountDeleted(cloud_account_id, workspace_id, account_id))
            case _:
                pass


def get_cloud_account_service(
    workspace_repository_dependency: WorkspaceRepositoryDependency,
    cloud_account_repository_dependency: CloudAccountRepositoryDependency,
    fix_dependency: FixDependency,
    domain_event_publisher_dependency: DomainEventPublisherDependency,
) -> CloudAccountService:
    redis_publisher = RedisPubSubPublisher(
        redis=fix_dependency.readwrite_redis, channel="cloud_accounts", publisher_name="cloud_account_service"
    )
    return CloudAccountServiceImpl(
        workspace_repository_dependency,
        cloud_account_repository_dependency,
        redis_publisher,
        domain_event_publisher_dependency,
    )


CloudAccountServiceDependency = Annotated[CloudAccountService, Depends(get_cloud_account_service)]
