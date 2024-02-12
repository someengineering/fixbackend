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
from typing import Annotated, Optional, Sequence

from fastapi import Depends
from fixcloudutils.redis.pub_sub import RedisPubSubPublisher
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fixbackend.auth.models import RoleName, User
from fixbackend.auth.role_repository import RoleRepository
from fixbackend.dependencies import FixDependency, ServiceNames
from fixbackend.domain_events.events import UserJoinedWorkspace, WorkspaceCreated
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.errors import NotAllowed
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import ExternalId, WorkspaceId, UserId, ProductTier
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.types import AsyncSessionMaker
from fixbackend.workspaces.models import Workspace, orm


class WorkspaceRepository(ABC):
    @abstractmethod
    async def create_workspace(self, name: str, slug: str, owner: User) -> Workspace:
        """Create a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def get_workspace(
        self, workspace_id: WorkspaceId, *, session: Optional[AsyncSession] = None
    ) -> Optional[Workspace]:
        """Get a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def list_workspaces(self, user_id: UserId) -> Sequence[Workspace]:
        """List all workspaces where the user is a member."""
        raise NotImplementedError

    @abstractmethod
    async def update_workspace(self, workspace_id: WorkspaceId, name: str, generate_external_id: bool) -> Workspace:
        """Update a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def add_to_workspace(self, workspace_id: WorkspaceId, user_id: UserId) -> None:
        """Add a user to a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def remove_from_workspace(self, workspace_id: WorkspaceId, user_id: UserId) -> None:
        """Remove a user from a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def update_security_tier(
        self, user: User, workspace_id: WorkspaceId, security_tier: ProductTier
    ) -> Workspace:
        """Update a workspace security tier."""
        raise NotImplementedError


class WorkspaceRepositoryImpl(WorkspaceRepository):
    def __init__(
        self,
        session_maker: AsyncSessionMaker,
        graph_db_access_manager: GraphDatabaseAccessManager,
        domain_event_sender: DomainEventPublisher,
        pubsub_publisher: RedisPubSubPublisher,
        subscription_repository: SubscriptionRepository,
        role_repository: RoleRepository,
    ) -> None:
        self.session_maker = session_maker
        self.graph_db_access_manager = graph_db_access_manager
        self.domain_event_sender = domain_event_sender
        self.pubsub_publisher = pubsub_publisher
        self.subscription_repository = subscription_repository
        self.role_repository = role_repository

    async def create_workspace(self, name: str, slug: str, owner: User) -> Workspace:
        async with self.session_maker() as session:
            workspace_id = WorkspaceId(uuid.uuid4())
            organization = orm.Organization(id=workspace_id, name=name, slug=slug, security_tier=ProductTier.Free.value)
            owner_relationship = orm.OrganizationOwners(user_id=owner.id)
            organization.owners.append(owner_relationship)
            session.add(organization)
            # create a database access object for this organization in the same transaction
            await self.graph_db_access_manager.create_database_access(workspace_id, session=session)
            await self.role_repository.add_roles(owner.id, workspace_id, RoleName.workspace_owner, session=session)
            await self.domain_event_sender.publish(WorkspaceCreated(workspace_id, owner.id))

            await session.commit()
            await session.refresh(organization)
            statement = (
                select(orm.Organization)
                .where(orm.Organization.id == organization.id)
                .options(selectinload(orm.Organization.owners), selectinload(orm.Organization.members))
            )
            results = await session.execute(statement)
            org = results.unique().scalar_one()
            return org.to_model()

    async def get_workspace(
        self, workspace_id: WorkspaceId, *, session: Optional[AsyncSession] = None
    ) -> Optional[Workspace]:
        async def get_ws(session: AsyncSession) -> Optional[Workspace]:
            statement = select(orm.Organization).where(orm.Organization.id == workspace_id)
            results = await session.execute(statement)
            org = results.unique().scalar_one_or_none()
            return org.to_model() if org else None

        if session is not None:
            return await get_ws(session)
        else:
            async with self.session_maker() as session:
                return await get_ws(session)

    async def update_workspace(self, workspace_id: WorkspaceId, name: str, generate_external_id: bool) -> Workspace:
        """Update a workspace."""
        async with self.session_maker() as session:
            statement = select(orm.Organization).where(orm.Organization.id == workspace_id)
            results = await session.execute(statement)
            org = results.unique().scalar_one_or_none()
            if org is None:
                raise ValueError(f"Organization {workspace_id} does not exist.")
            org.name = name
            if generate_external_id:
                org.external_id = ExternalId(uuid.uuid4())
            await session.commit()
            await session.refresh(org)
            return org.to_model()

    async def list_workspaces(self, user_id: UserId) -> Sequence[Workspace]:
        async with self.session_maker() as session:
            statement = (
                select(orm.Organization)
                .join(
                    orm.OrganizationOwners, orm.Organization.id == orm.OrganizationOwners.organization_id, isouter=True
                )
                .join(
                    orm.OrganizationMembers,
                    orm.Organization.id == orm.OrganizationMembers.organization_id,
                    isouter=True,
                )
                .where(or_(orm.OrganizationOwners.user_id == user_id, orm.OrganizationMembers.user_id == user_id))
            )
            results = await session.execute(statement)
            orgs = results.unique().scalars().all()
            return [org.to_model() for org in orgs]

    async def add_to_workspace(self, workspace_id: WorkspaceId, user_id: UserId) -> None:
        async with self.session_maker() as session:
            existing_membership = await session.get(orm.OrganizationMembers, (workspace_id, user_id))
            if existing_membership is not None:
                # user is already a member of the organization, do nothing
                return None

            member_relationship = orm.OrganizationMembers(user_id=user_id, organization_id=workspace_id)
            session.add(member_relationship)
            try:
                await session.commit()
            except IntegrityError:
                raise ValueError("Can't add user to workspace.")

        event = UserJoinedWorkspace(workspace_id, user_id)
        await self.domain_event_sender.publish(event)
        await self.pubsub_publisher.publish(event.kind, event.to_json(), f"tenant-events::{event.workspace_id}")

    async def remove_from_workspace(self, workspace_id: WorkspaceId, user_id: UserId) -> None:
        async with self.session_maker() as session:
            membership = await session.get(orm.OrganizationMembers, (workspace_id, user_id))
            if membership is None:
                raise ValueError(f"User {user_id} is not a member of workspace {workspace_id}")
            await session.delete(membership)
            await session.commit()

    async def update_security_tier(
        self, user: User, workspace_id: WorkspaceId, security_tier: ProductTier
    ) -> Workspace:
        async with self.session_maker() as session:
            statement = select(orm.Organization).where(orm.Organization.id == workspace_id)
            results = await session.execute(statement)
            org = results.unique().scalar_one_or_none()
            if org is None:
                raise ValueError(f"Organization {workspace_id} does not exist.")

            subscription = await anext(
                self.subscription_repository.subscriptions(workspace_id=workspace_id, session=session), None
            )
            if subscription is None:
                raise NotAllowed("Organization must have a subscription to change the security tier")

            org.security_tier = security_tier.value
            await session.commit()
            await session.refresh(org)

            return org.to_model()


async def get_workspace_repository(fix: FixDependency) -> WorkspaceRepository:
    return fix.service(ServiceNames.workspace_repo, WorkspaceRepositoryImpl)


WorkspaceRepositoryDependency = Annotated[WorkspaceRepository, Depends(get_workspace_repository)]
