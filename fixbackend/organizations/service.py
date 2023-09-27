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
from datetime import datetime, timedelta
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fixbackend.auth.models import User, orm as auth_orm
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import TenantId, UserId
from fixbackend.organizations.models import Organization, OrganizationInvite, orm


class OrganizationService:
    def __init__(self, session: AsyncSession, graph_db_access_manager: GraphDatabaseAccessManager) -> None:
        self.session = session
        self.graph_db_access_manager = graph_db_access_manager

    async def create_organization(self, name: str, slug: str, owner: User) -> Organization:
        """Create an organization."""
        tenant_id = TenantId(uuid.uuid4())
        organization = orm.Organization(id=tenant_id, name=name, slug=slug)
        owner_relationship = orm.OrganizationOwners(user_id=owner.id)
        organization.owners.append(owner_relationship)
        self.session.add(organization)
        # create a database access object for this organization in the same transaction
        await self.graph_db_access_manager.create_database_access(tenant_id, session=self.session)

        await self.session.commit()
        await self.session.refresh(organization)
        statement = (
            select(orm.Organization)
            .where(orm.Organization.id == organization.id)
            .options(selectinload(orm.Organization.owners), selectinload(orm.Organization.members))
        )
        results = await self.session.execute(statement)
        org = results.unique().scalar_one()
        return org.to_domain()

    async def get_organization(self, organization_id: TenantId, with_users: bool = False) -> Optional[Organization]:
        """Get an organization."""
        statement = select(orm.Organization).where(orm.Organization.id == organization_id)
        if with_users:
            statement = statement.options(selectinload(orm.Organization.owners), selectinload(orm.Organization.members))
        results = await self.session.execute(statement)
        org = results.unique().scalar_one_or_none()
        return org.to_domain() if org else None

    async def list_organizations(self, user_id: UserId, with_users: bool = False) -> Sequence[Organization]:
        """List all organizations where the user is an owner."""
        statement = (
            select(orm.Organization).join(orm.OrganizationOwners).where(orm.OrganizationOwners.user_id == user_id)
        )
        if with_users:
            statement = statement.options(selectinload(orm.Organization.owners), selectinload(orm.Organization.members))
        results = await self.session.execute(statement)
        orgs = results.scalars().all()
        return [org.to_domain() for org in orgs]

    async def add_to_organization(self, organization_id: TenantId, user_id: UserId) -> None:
        """Add a user to an organization."""

        existing_membership = await self.session.get(orm.OrganizationMembers, (organization_id, user_id))
        if existing_membership is not None:
            # user is already a member of the organization, do nothing
            return None

        member_relationship = orm.OrganizationMembers(user_id=user_id, organization_id=organization_id)
        self.session.add(member_relationship)
        try:
            await self.session.commit()
        except IntegrityError:
            raise ValueError("Can't add user to organization.")

    async def remove_from_organization(self, organization_id: TenantId, user_id: UserId) -> None:
        """Remove a user from an organization."""
        membership = await self.session.get(orm.OrganizationMembers, (organization_id, user_id))
        if membership is None:
            raise ValueError(f"User {uuid} is not a member of organization {organization_id}")
        await self.session.delete(membership)
        await self.session.commit()

    async def create_invitation(self, organization_id: TenantId, user_id: UserId) -> OrganizationInvite:
        """Create an invite for an organization."""
        user = await self.session.get(auth_orm.User, user_id)
        organization = await self.get_organization(organization_id, with_users=True)

        if user is None or organization is None:
            raise ValueError(f"User {user_id} or organization {organization_id} does not exist.")

        if user.id in [owner for owner in organization.owners]:
            raise ValueError(f"User {user_id} is already an owner of organization {organization_id}")

        if user.id in [member for member in organization.members]:
            raise ValueError(f"User {user_id} is already a member of organization {organization_id}")

        invite = orm.OrganizationInvite(
            user_id=user_id, organization_id=organization_id, expires_at=datetime.utcnow() + timedelta(days=7)
        )
        self.session.add(invite)
        await self.session.commit()
        await self.session.refresh(invite)
        return invite.to_domain()

    async def get_invitation(self, invitation_id: uuid.UUID) -> Optional[OrganizationInvite]:
        """Get an invitation by ID."""
        statement = (
            select(orm.OrganizationInvite)
            .where(orm.OrganizationInvite.id == invitation_id)
            .options(selectinload(orm.OrganizationInvite.user))
        )
        results = await self.session.execute(statement)
        invite = results.unique().scalar_one_or_none()
        return invite.to_domain() if invite else None

    async def list_invitations(self, organization_id: TenantId) -> Sequence[OrganizationInvite]:
        """List all invitations for an organization."""
        statement = (
            select(orm.OrganizationInvite)
            .where(orm.OrganizationInvite.organization_id == organization_id)
            .options(selectinload(orm.OrganizationInvite.user), selectinload(orm.OrganizationInvite.organization))
        )
        results = await self.session.execute(statement)
        invites = results.scalars().all()
        return [invite.to_domain() for invite in invites]

    async def accept_invitation(self, invitation_id: uuid.UUID) -> None:
        """Accept an invitation to an organization."""
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
        """Delete an invitation."""
        invite = await self.session.get(orm.OrganizationInvite, invitation_id)
        if invite is None:
            raise ValueError(f"Invitation {invitation_id} does not exist.")
        await self.session.delete(invite)
        await self.session.commit()
