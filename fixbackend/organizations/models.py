from typing import Set, Optional, NewType
from datetime import datetime

from sqlalchemy.orm import Mapped, relationship, declared_attr, mapped_column
from sqlalchemy import ForeignKey, String, DateTime, Boolean, Integer, func, select, Column, Table  
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from fixbackend.auth.models import User
from fixbackend.base_model import Base



class Organization(Base):

    __tablename__ = "organization"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(length=320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(length=320), nullable=False)
    owners: Mapped[Set["OrganizationOwners"]] = relationship(back_populates="organization")
    members: Mapped[Set["OrganizationMembers"]] = relationship(back_populates="organization")


class OrganizationInvite(Base):

    __tablename__ = "organization_invite"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organization.id"), nullable=False)
    organization: Mapped[Organization] = relationship(lazy="joined")
    user_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("user.id"), nullable=False)
    user: Mapped[User] = relationship(lazy="joined")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OrganizationOwners(Base):
    """
    Many-to-many relationship between organizations and owners.
    """

    __tablename__ = "organization_owners"

    organization_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organization.id"), primary_key=True)
    organization: Mapped[Organization] = relationship(back_populates="owners", lazy="joined")
    user_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("user.id"), primary_key=True)
    user: Mapped[User] = relationship(lazy="joined")


class OrganizationMembers(Base):
    """
    Many-to-many relationship between organizations and members.
    """

    __tablename__ = "organization_members"

    organization_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organization.id"), primary_key=True)
    organization: Mapped[Organization] = relationship(back_populates="members", lazy="joined")
    user_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("user.id"), primary_key=True)
    user: Mapped[User] = relationship(lazy="joined")

