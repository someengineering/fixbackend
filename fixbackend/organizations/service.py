from typing import Optional
from abc import abstractmethod, ABCMeta
import uuid

from fixbackend.organizations.models import Organization, OrganizationInvite, OrganizationOwners, OrganizationMembers
from fixbackend.auth.models import User
from fixbackend.organizations import models
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta, timezone


class OrganizationService(metaclass=ABCMeta):

    @abstractmethod
    async def create_organization(self, name: str, owner_id: uuid.UUID) -> Organization:
        """Create an organization."""
        raise NotImplementedError()
    
    @abstractmethod
    async def get_organization(self, organization_id: uuid.UUID, with_users: bool = False) -> Optional[Organization]:
        """Get an organization."""
        raise NotImplementedError()

    @abstractmethod
    async def add_to_organization(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Add a user to an organization."""
        raise NotImplementedError() 

    @abstractmethod
    async def remove_from_organization(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Remove a user from an organization."""
        raise NotImplementedError()
    
    @abstractmethod
    async def create_invitation(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> OrganizationInvite:
        """Create an invite for an organization."""
        raise NotImplementedError()
    
    @abstractmethod
    async def accept_invitation(self, invitation_id: uuid.UUID) -> None:
        """Accept an invitation to an organization."""
        raise NotImplementedError()
    

class OrganizationServiceImpl(OrganizationService):

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_organization(self, name: str, slug: str, owner: User) -> models.Organization:
        """Create an organization."""
        organization = Organization(name=name, slug=slug)
        owner_relationship = OrganizationOwners(user_id=owner.id)
        organization.owners.add(owner_relationship)
        self.session.add(organization)

        await self.session.commit()
        await self.session.refresh(organization)
        statement = (select(Organization)
                    .where(Organization.id == organization.id)
                    .options(
                        selectinload(Organization.owners), 
                        selectinload(Organization.members)
                    ))
        results = await self.session.execute(statement)
        return results.unique().scalar_one()
    
    async def get_organization(self, organization_id: uuid.UUID, with_users: bool=False) -> Optional[Organization]:
        """Get an organization."""
        statement = select(Organization).where(Organization.id == organization_id)
        if with_users:
            statement = statement.options(
                selectinload(Organization.owners), 
                selectinload(Organization.members)
            )
        results = await self.session.execute(statement)
        return results.unique().scalar_one_or_none()

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
        organization = await self.session.get(Organization, organization_id)
        if user is None or organization is None:
            raise ValueError(f"User {user_id} or organization {organization_id} does not exist.")
        
        invite = OrganizationInvite(user_id=user_id, organization_id=organization_id, expires_at=datetime.utcnow() + timedelta(days=7))
        self.session.add(invite)
        await self.session.commit()
        await self.session.refresh(invite)
        return invite
    
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