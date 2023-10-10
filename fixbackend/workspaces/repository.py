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
from datetime import datetime, timedelta
from typing import Annotated, Optional, Sequence

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fixbackend.auth.models import User
from fixbackend.auth.models import orm as auth_orm
from fixbackend.db import AsyncSessionDependency
from fixbackend.dependencies import FixDependency
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import WorkspaceId, UserId
from fixbackend.workspaces.models import Workspace, WorkspaceInvite, orm


class WorkspaceRepository(ABC):
    @abstractmethod
    async def create_workspace(self, name: str, slug: str, owner: User) -> Workspace:
        """Create a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def get_workspace(self, workspace_id: WorkspaceId) -> Optional[Workspace]:
        """Get a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def list_workspaces(self, user_id: UserId) -> Sequence[Workspace]:
        """List all workspaces where the user is a member."""
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
    async def create_invitation(self, workspace_id: WorkspaceId, user_id: UserId) -> WorkspaceInvite:
        """Create an invite for a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def get_invitation(self, invitation_id: uuid.UUID) -> Optional[WorkspaceInvite]:
        """Get an invitation by ID."""
        raise NotImplementedError

    @abstractmethod
    async def list_invitations(self, workspace_id: WorkspaceId) -> Sequence[WorkspaceInvite]:
        """List all invitations for a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def accept_invitation(self, invitation_id: uuid.UUID) -> None:
        """Accept an invitation to a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def delete_invitation(self, invitation_id: uuid.UUID) -> None:
        """Delete an invitation."""
        raise NotImplementedError


class WorkspaceRepositoryImpl(WorkspaceRepository):
    def __init__(self, session: AsyncSession, graph_db_access_manager: GraphDatabaseAccessManager) -> None:
        self.session = session
        self.graph_db_access_manager = graph_db_access_manager

    async def create_workspace(self, name: str, slug: str, owner: User) -> Workspace:
        workspace_id = WorkspaceId(uuid.uuid4())
        organization = orm.Organization(id=workspace_id, name=name, slug=slug)
        owner_relationship = orm.OrganizationOwners(user_id=owner.id)
        organization.owners.append(owner_relationship)
        self.session.add(organization)
        # create a database access object for this organization in the same transaction
        await self.graph_db_access_manager.create_database_access(workspace_id, session=self.session)

        await self.session.commit()
        await self.session.refresh(organization)
        statement = (
            select(orm.Organization)
            .where(orm.Organization.id == organization.id)
            .options(selectinload(orm.Organization.owners), selectinload(orm.Organization.members))
        )
        results = await self.session.execute(statement)
        org = results.unique().scalar_one()
        return org.to_model()

    async def get_workspace(self, workspace_id: WorkspaceId) -> Optional[Workspace]:
        statement = select(orm.Organization).where(orm.Organization.id == workspace_id)
        results = await self.session.execute(statement)
        org = results.unique().scalar_one_or_none()
        return org.to_model() if org else None

    async def list_workspaces(self, user_id: UserId) -> Sequence[Workspace]:
        statement = (
            select(orm.Organization).join(orm.OrganizationOwners).where(orm.OrganizationOwners.user_id == user_id)
        )
        results = await self.session.execute(statement)
        orgs = results.unique().scalars().all()
        return [org.to_model() for org in orgs]

    async def add_to_workspace(self, workspace_id: WorkspaceId, user_id: UserId) -> None:
        existing_membership = await self.session.get(orm.OrganizationMembers, (workspace_id, user_id))
        if existing_membership is not None:
            # user is already a member of the organization, do nothing
            return None

        member_relationship = orm.OrganizationMembers(user_id=user_id, organization_id=workspace_id)
        self.session.add(member_relationship)
        try:
            await self.session.commit()
        except IntegrityError:
            raise ValueError("Can't add user to workspace.")

    async def remove_from_workspace(self, workspace_id: WorkspaceId, user_id: UserId) -> None:
        membership = await self.session.get(orm.OrganizationMembers, (workspace_id, user_id))
        if membership is None:
            raise ValueError(f"User {uuid} is not a member of workspace {workspace_id}")
        await self.session.delete(membership)
        await self.session.commit()

    async def create_invitation(self, workspace_id: WorkspaceId, user_id: UserId) -> WorkspaceInvite:
        user = await self.session.get(auth_orm.User, user_id)
        organization = await self.get_workspace(workspace_id)

        if user is None or organization is None:
            raise ValueError(f"User {user_id} or organization {workspace_id} does not exist.")

        if user.id in [owner for owner in organization.owners]:
            raise ValueError(f"User {user_id} is already an owner of workspace {workspace_id}")

        if user.id in [member for member in organization.members]:
            raise ValueError(f"User {user_id} is already a member of workspace {workspace_id}")

        invite = orm.OrganizationInvite(
            user_id=user_id, organization_id=workspace_id, expires_at=datetime.utcnow() + timedelta(days=7)
        )
        self.session.add(invite)
        await self.session.commit()
        await self.session.refresh(invite)
        return invite.to_model()

    async def get_invitation(self, invitation_id: uuid.UUID) -> Optional[WorkspaceInvite]:
        statement = (
            select(orm.OrganizationInvite)
            .where(orm.OrganizationInvite.id == invitation_id)
            .options(selectinload(orm.OrganizationInvite.user))
        )
        results = await self.session.execute(statement)
        invite = results.unique().scalar_one_or_none()
        return invite.to_model() if invite else None

    async def list_invitations(self, workspace_id: WorkspaceId) -> Sequence[WorkspaceInvite]:
        statement = (
            select(orm.OrganizationInvite)
            .where(orm.OrganizationInvite.organization_id == workspace_id)
            .options(selectinload(orm.OrganizationInvite.user), selectinload(orm.OrganizationInvite.organization))
        )
        results = await self.session.execute(statement)
        invites = results.scalars().all()
        return [invite.to_model() for invite in invites]

    async def accept_invitation(self, invitation_id: uuid.UUID) -> None:
        invite = await self.session.get(orm.OrganizationInvite, invitation_id)
        if invite is None:
            raise ValueError(f"Invitation {invitation_id} does not exist.")
        if invite.expires_at < datetime.utcnow():
            raise ValueError(f"Invitation {invitation_id} has expired.")
        membership = orm.OrganizationMembers(user_id=invite.user_id, organization_id=invite.organization_id)
        self.session.add(membership)
        await self.session.delete(invite)
        await self.session.commit()

    async def delete_invitation(self, invitation_id: uuid.UUID) -> None:
        invite = await self.session.get(orm.OrganizationInvite, invitation_id)
        if invite is None:
            raise ValueError(f"Invitation {invitation_id} does not exist.")
        await self.session.delete(invite)
        await self.session.commit()


async def get_workspace_repository(session: AsyncSessionDependency, fix: FixDependency) -> WorkspaceRepository:
    return WorkspaceRepositoryImpl(session, fix.graph_database_access)


WorkspaceRepositoryDependency = Annotated[WorkspaceRepository, Depends(get_workspace_repository)]