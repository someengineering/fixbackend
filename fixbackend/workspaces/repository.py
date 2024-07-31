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

import calendar
import uuid
from abc import ABC, abstractmethod
from logging import getLogger
from typing import Annotated, Optional, Sequence

from attrs import evolve
from fastapi import Depends
from fixcloudutils.redis.pub_sub import RedisPubSubPublisher
from sqlalchemy import or_, select, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fixbackend.auth.models import User
from fixbackend.permissions.models import Roles, WorkspacePermissions
from fixbackend.permissions.validator import validate_workspace_permissions
from fixbackend.permissions.role_repository import RoleRepository
from fixbackend.dependencies import FixDependency, ServiceNames
from fixbackend.domain_events.events import UserJoinedWorkspace, WorkspaceCreated
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.errors import NotAllowed, ResourceNotFound, WrongState
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import ExternalId, SubscriptionId, WorkspaceId, UserId, ProductTier
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.types import AsyncSessionMaker
from fixbackend.workspaces.models import Workspace, orm
from datetime import datetime, timedelta, timezone
from fixcloudutils.util import utc

log = getLogger(__name__)


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
    async def list_workspaces(self, user: User, can_assign_subscriptions: bool = False) -> Sequence[Workspace]:
        """List all workspaces where the user is a member."""
        raise NotImplementedError

    @abstractmethod
    async def update_workspace(self, workspace_id: WorkspaceId, name: str, generate_external_id: bool) -> Workspace:
        """Update a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def add_to_workspace(self, workspace_id: WorkspaceId, user_id: UserId, role: Roles) -> None:
        """Add a user to a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def remove_from_workspace(self, workspace_id: WorkspaceId, user_id: UserId) -> None:
        """Remove a user from a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def get_product_tier(self, workspace_id: WorkspaceId) -> ProductTier:
        """Get the product tier of the workspace"""
        raise NotImplementedError

    @abstractmethod
    async def update_product_tier(
        self, workspace_id: WorkspaceId, new_tier: ProductTier, *, session: Optional[AsyncSession] = None
    ) -> Workspace:
        """Update a workspace security tier."""
        raise NotImplementedError

    @abstractmethod
    async def list_workspaces_by_subscription_id(self, subscription_id: SubscriptionId) -> Sequence[Workspace]:
        """List all workspaces with the assigned subscription."""
        raise NotImplementedError

    @abstractmethod
    async def update_subscription(
        self,
        workspace_id: WorkspaceId,
        subscription_id: Optional[SubscriptionId],
        *,
        session: Optional[AsyncSession] = None,
    ) -> Workspace:
        """Assign a subscription to a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def update_payment_on_hold(self, workspace_id: WorkspaceId, on_hold_since: Optional[datetime]) -> Workspace:
        """Set the payment on hold for a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def list_by_on_hold(self, before: datetime) -> Sequence[Workspace]:
        """List all workspaces with the payment on hold marker before the given date."""
        raise NotImplementedError

    @abstractmethod
    async def list_expired_trials(
        self, been_in_trial_tier_for: timedelta, *, session: Optional[AsyncSession] = None
    ) -> Sequence[Workspace]:
        """List all workspaces which have been in trial for mor that provided time."""
        raise NotImplementedError

    @abstractmethod
    async def ack_move_to_free(self, workspace_id: WorkspaceId, user_id: UserId) -> Workspace:
        """Acknowledge that the workspace moved to free tier."""
        raise NotImplementedError

    @abstractmethod
    async def list_overdue_free_tier_cleanup(self, been_in_free_tier_for: timedelta) -> Sequence[Workspace]:
        """List all workspaces where the free tier cleanup is overdue."""
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

            # get workspace by slug
            statement = select(orm.Organization).where(orm.Organization.slug == slug)
            slug_exists = (await session.execute(statement)).unique().scalar_one_or_none()
            if slug_exists:
                slug = f"{slug}-{workspace_id}"

            organization = orm.Organization(
                id=workspace_id,
                name=name,
                slug=slug,
                tier=ProductTier.Trial.value,
                owner_id=owner.id,
                tier_updated_at=utc(),
            )
            member_relationship = orm.OrganizationMembers(user_id=owner.id)
            organization.members.append(member_relationship)
            session.add(organization)
            # create a database access object for this organization in the same transaction
            await self.graph_db_access_manager.create_database_access(workspace_id, session=session)
            await self.role_repository.add_roles(owner.id, workspace_id, Roles.workspace_owner, session=session)
            await self.domain_event_sender.publish(WorkspaceCreated(workspace_id, name, slug, owner.id))

            await session.commit()
            await session.refresh(organization)
            log.info(f"Created workspace {workspace_id}, owner {owner.id}")
            statement = (
                select(orm.Organization)
                .where(orm.Organization.id == organization.id)
                .options(selectinload(orm.Organization.members))
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
                raise ResourceNotFound(f"Organization {workspace_id} does not exist.")
            org.name = name
            if generate_external_id:
                org.external_id = ExternalId(uuid.uuid4())
            await session.commit()
            await session.refresh(org)
            return org.to_model()

    async def list_workspaces(self, user: User, can_assign_subscriptions: bool = False) -> Sequence[Workspace]:
        async with self.session_maker() as session:
            statement = (
                select(orm.Organization, orm.UserTrialNotificationStatus.created_at)
                .join(
                    orm.OrganizationMembers,
                    orm.Organization.id == orm.OrganizationMembers.organization_id,
                    isouter=True,
                )
                .outerjoin(
                    orm.UserTrialNotificationStatus,
                    and_(
                        orm.Organization.id == orm.UserTrialNotificationStatus.workspace_id,
                        orm.UserTrialNotificationStatus.user_id == user.id,
                    ),
                )
                .where(or_(orm.Organization.owner_id == user.id, orm.OrganizationMembers.user_id == user.id))
            )
            results = await session.execute(statement)
            entities = results.unique().all()
            workspaces = [entity[0].to_model(entity[1]) for entity in entities]

            if can_assign_subscriptions:
                result = []
                for workspace in workspaces:
                    if validate_workspace_permissions(user, workspace.id, WorkspacePermissions.update_billing) is None:
                        result.append(workspace)
                return result
            else:
                return workspaces

    async def list_workspaces_by_subscription_id(self, subscription_id: SubscriptionId) -> Sequence[Workspace]:
        async with self.session_maker() as session:
            statement = select(orm.Organization).where(orm.Organization.subscription_id == subscription_id)
            results = await session.execute(statement)
            orgs = results.unique().scalars().all()
            return [org.to_model() for org in orgs]

    async def update_subscription(
        self,
        workspace_id: WorkspaceId,
        subscription_id: Optional[SubscriptionId],
        *,
        session: Optional[AsyncSession] = None,
    ) -> Workspace:

        async def do_tx(session: AsyncSession) -> Workspace:
            statement = select(orm.Organization).where(orm.Organization.id == workspace_id)
            results = await session.execute(statement)
            workspace = results.unique().scalar_one_or_none()
            if workspace is None:
                raise ResourceNotFound(f"Organization {workspace_id} does not exist.")
            workspace.subscription_id = subscription_id
            await session.commit()
            await session.refresh(workspace)
            return workspace.to_model()

        if session:
            return await do_tx(session)
        else:
            async with self.session_maker() as session:
                return await do_tx(session)

    async def add_to_workspace(self, workspace_id: WorkspaceId, user_id: UserId, role: Roles) -> None:
        async with self.session_maker() as session:
            existing_membership = await session.get(orm.OrganizationMembers, (workspace_id, user_id))
            if existing_membership is not None:
                # user is already a member of the organization, do nothing
                return None

            member_relationship = orm.OrganizationMembers(user_id=user_id, organization_id=workspace_id)
            session.add(member_relationship)
            await self.role_repository.add_roles(user_id, workspace_id, role, session=session)
            try:
                await session.commit()
            except IntegrityError:
                raise WrongState("User is already a member of the workspace")

        event = UserJoinedWorkspace(workspace_id, user_id)
        await self.domain_event_sender.publish(event)
        await self.pubsub_publisher.publish(event.kind, event.to_json(), f"tenant-events::{event.workspace_id}")

    async def remove_from_workspace(self, workspace_id: WorkspaceId, user_id: UserId) -> None:
        async with self.session_maker() as session:
            membership = await session.get(orm.OrganizationMembers, (workspace_id, user_id))
            if membership is None:
                # no one to remove
                log.info("Removing user %s from workspace %s, but they are not a member. Ignoring.")
                return None
            await session.delete(membership)
            await session.commit()

    async def get_product_tier(self, workspace_id: WorkspaceId) -> ProductTier:
        workspace = await self.get_workspace(workspace_id)
        if workspace is None:
            raise ResourceNotFound(f"Organization {workspace_id} does not exist.")

        return workspace.current_product_tier()

    async def update_product_tier(
        self, workspace_id: WorkspaceId, new_tier: ProductTier, *, session: Optional[AsyncSession] = None
    ) -> Workspace:
        async def do_tx(session: AsyncSession) -> Workspace:
            statement = select(orm.Organization).where(orm.Organization.id == workspace_id)
            results = await session.execute(statement)
            workspace = results.unique().scalar_one_or_none()
            if workspace is None:
                raise ResourceNotFound(f"Organization {workspace_id} does not exist.")

            if workspace.subscription_id is None and new_tier.paid:
                raise NotAllowed("Workspace must have a subscription to change the security tier")

            workspace.tier = new_tier.value
            active_tier = ProductTier.from_str(workspace.highest_current_cycle_tier or ProductTier.Free.value)
            if workspace.highest_current_cycle_tier is None or active_tier < new_tier:
                now = utc()
                _, last_day_of_the_month = calendar.monthrange(now.year, now.month)
                last_billing_cycle_instant = datetime(
                    now.year, now.month, last_day_of_the_month, 23, 59, 59, 999999, timezone.utc
                )
                workspace.current_cycle_ends_at = last_billing_cycle_instant
            workspace.highest_current_cycle_tier = max(active_tier, new_tier)
            workspace.tier_updated_at = utc()

            await session.commit()
            await session.refresh(workspace)

            return workspace.to_model()

        if session:
            return await do_tx(session)
        else:
            async with self.session_maker() as session:
                return await do_tx(session)

    async def update_payment_on_hold(self, workspace_id: WorkspaceId, on_hold_since: Optional[datetime]) -> Workspace:
        """Set the payment on hold for a workspace."""
        async with self.session_maker() as session:
            statement = select(orm.Organization).where(orm.Organization.id == workspace_id)
            results = await session.execute(statement)
            workspace = results.unique().scalar_one_or_none()
            if workspace is None:
                raise ResourceNotFound(f"Organization {workspace_id} does not exist.")

            workspace.payment_on_hold_since = on_hold_since
            await session.commit()
            await session.refresh(workspace)

            return workspace.to_model()

    async def list_by_on_hold(self, before: datetime) -> Sequence[Workspace]:
        """List all workspaces with the payment on hold earlier the given date."""
        async with self.session_maker() as session:
            statement = select(orm.Organization).where(orm.Organization.payment_on_hold_since < before)
            results = await session.execute(statement)
            workspaces = results.unique().scalars().all()
            return [ws.to_model() for ws in workspaces]

    async def list_expired_trials(
        self, been_in_trial_tier_for: timedelta, *, session: Optional[AsyncSession] = None
    ) -> Sequence[Workspace]:
        """List all workspaces with the trial expired before the given date."""

        async def do_tx(session: AsyncSession) -> Sequence[Workspace]:
            statement = (
                select(orm.Organization)
                .where(orm.Organization.tier == ProductTier.Trial.value)
                .where(orm.Organization.created_at < utc() - been_in_trial_tier_for)
            )
            results = await session.execute(statement)
            workspaces = results.unique().scalars().all()
            return [ws.to_model() for ws in workspaces]

        if session:
            return await do_tx(session)
        else:
            async with self.session_maker() as session:
                return await do_tx(session)

    async def ack_move_to_free(self, workspace_id: WorkspaceId, user_id: UserId) -> Workspace:
        """Acknowledge that the workspace moved to free tier."""
        async with self.session_maker() as session:
            workspace_statement = select(orm.Organization).where(orm.Organization.id == workspace_id)
            workspace_entity = (await session.execute(workspace_statement)).unique().scalar_one_or_none()
            if workspace_entity is None:
                raise ResourceNotFound(f"Organization {workspace_id} does not exist.")

            workspace = workspace_entity.to_model()

            if user_id not in workspace.all_users():
                raise NotAllowed("user_not_in_workspace")

            if workspace.current_product_tier() != ProductTier.Free.value:
                raise NotAllowed("wrong_tier")

            notification_statement = (
                select(orm.UserTrialNotificationStatus)
                .where(orm.UserTrialNotificationStatus.workspace_id == workspace_id)
                .where(orm.UserTrialNotificationStatus.user_id == user_id)
            )
            notification_results = await session.execute(notification_statement)
            notification_status = notification_results.unique().scalar_one_or_none()

            if notification_status is not None:
                return evolve(workspace, move_to_free_acknowledged_at=notification_status.created_at)

            now = utc()
            session.add(orm.UserTrialNotificationStatus(workspace_id=workspace_id, user_id=user_id, created_at=now))
            await session.commit()

            return evolve(workspace, move_to_free_acknowledged_at=now)

    async def list_overdue_free_tier_cleanup(self, been_in_free_tier_for: timedelta) -> Sequence[Workspace]:
        """List all workspaces where the free tier cleanup is overdue."""
        async with self.session_maker() as session:
            statement = (
                select(orm.Organization)
                .where(orm.Organization.tier == ProductTier.Free.value)
                .where(orm.Organization.tier_updated_at < utc() - been_in_free_tier_for)
                .where(orm.Organization.tier_updated_at > utc() - been_in_free_tier_for - timedelta(days=1))
            )
            results = await session.execute(statement)
            workspaces = results.unique().scalars().all()
            return [ws.to_model() for ws in workspaces]


async def get_workspace_repository(fix: FixDependency) -> WorkspaceRepository:
    return fix.service(ServiceNames.workspace_repo, WorkspaceRepositoryImpl)


WorkspaceRepositoryDependency = Annotated[WorkspaceRepository, Depends(get_workspace_repository)]
