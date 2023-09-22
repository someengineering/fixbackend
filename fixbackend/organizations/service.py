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
from typing import Optional, Sequence, Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fixbackend.auth.models import User
from fixbackend.db import get_async_session
from fixbackend.organizations import models
from fixbackend.organizations.models import Organization, OrganizationInvite, OrganizationOwners, OrganizationMembers


class OrganizationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_organization(self, name: str, slug: str, owner: User) -> models.Organization:
        """Create an organization."""
        organization = Organization(name=name, slug=slug)
        owner_relationship = OrganizationOwners(user_id=owner.id)
        organization.owners.append(owner_relationship)
        self.session.add(organization)

        await self.session.commit()
        await self.session.refresh(organization)
        statement = (
            select(Organization)
            .where(Organization.id == organization.id)
            .options(selectinload(Organization.owners), selectinload(Organization.members))
        )
        results = await self.session.execute(statement)
        return results.unique().scalar_one()

    async def get_organization(self, organization_id: uuid.UUID, with_users: bool = False) -> Optional[Organization]:
        """Get an organization."""
        statement = select(Organization).where(Organization.id == organization_id)
        if with_users:
            statement = statement.options(selectinload(Organization.owners), selectinload(Organization.members))
        results = await self.session.execute(statement)
        return results.unique().scalar_one_or_none()

    async def list_organizations(self, user_id: uuid.UUID, with_users: bool = False) -> Sequence[Organization]:
        """List all organizations where the user is an owner."""
        statement = select(Organization).join(OrganizationOwners).where(OrganizationOwners.user_id == user_id)
        if with_users:
            statement = statement.options(selectinload(Organization.owners), selectinload(Organization.members))
        results = await self.session.execute(statement)
        return results.scalars().all()

    async def add_to_organization(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Add a user to an organization."""

        existing_membership = await self.session.get(OrganizationMembers, (organization_id, user_id))
        if existing_membership is not None:
            # user is already a member of the organization, do nothing
            return None

        member_relationship = OrganizationMembers(user_id=user_id, organization_id=organization_id)
        self.session.add(member_relationship)
        try:
            await self.session.commit()
        except IntegrityError:
            raise ValueError("Can't add user to organization.")

    async def remove_from_organization(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Remove a user from an organization."""
        membership = await self.session.get(OrganizationMembers, (organization_id, user_id))
        if membership is None:
            raise ValueError(f"User {uuid} is not a member of organization {organization_id}")
        await self.session.delete(membership)
        await self.session.commit()

    async def create_invitation(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> OrganizationInvite:
        """Create an invite for an organization."""
        user = await self.session.get(User, user_id)
        organization = await self.get_organization(organization_id, with_users=True)

        if user is None or organization is None:
            raise ValueError(f"User {user_id} or organization {organization_id} does not exist.")

        if user.email in [owner.user.email for owner in organization.owners]:
            raise ValueError(f"User {user_id} is already an owner of organization {organization_id}")

        if user.email in [member.user.email for member in organization.members]:
            raise ValueError(f"User {user_id} is already a member of organization {organization_id}")

        invite = OrganizationInvite(
            user_id=user_id, organization_id=organization_id, expires_at=datetime.utcnow() + timedelta(days=7)
        )
        self.session.add(invite)
        await self.session.commit()
        await self.session.refresh(invite)
        return invite

    async def get_invitation(self, invitation_id: uuid.UUID) -> Optional[OrganizationInvite]:
        """Get an invitation by ID."""
        statement = (
            select(OrganizationInvite)
            .where(OrganizationInvite.id == invitation_id)
            .options(selectinload(OrganizationInvite.user))
        )
        results = await self.session.execute(statement)
        return results.unique().scalar_one_or_none()

    async def list_invitations(self, organization_id: uuid.UUID) -> Sequence[OrganizationInvite]:
        """List all invitations for an organization."""
        statement = (
            select(OrganizationInvite)
            .where(OrganizationInvite.organization_id == organization_id)
            .options(selectinload(OrganizationInvite.user), selectinload(OrganizationInvite.organization))
        )
        results = await self.session.execute(statement)
        return results.scalars().all()

    async def accept_invitation(self, invitation_id: uuid.UUID) -> None:
        """Accept an invitation to an organization."""
        invite = await self.session.get(OrganizationInvite, invitation_id)
        if invite is None:
            raise ValueError(f"Invitation {invitation_id} does not exist.")
        if invite.expires_at < datetime.utcnow():
            raise ValueError(f"Invitation {invitation_id} has expired.")
        membership = OrganizationMembers(user_id=invite.user_id, organization_id=invite.organization_id)
        self.session.add(membership)
        await self.session.delete(invite)
        await self.session.commit()

    async def delete_invitation(self, invitation_id: uuid.UUID) -> None:
        """Delete an invitation."""
        invite = await self.session.get(OrganizationInvite, invitation_id)
        if invite is None:
            raise ValueError(f"Invitation {invitation_id} does not exist.")
        await self.session.delete(invite)
        await self.session.commit()


async def get_organization_service(session: Annotated[AsyncSession, Depends(get_async_session)]) -> OrganizationService:
    return OrganizationService(session)


OrganizationServiceDependency = Annotated[OrganizationService, Depends(get_organization_service)]
