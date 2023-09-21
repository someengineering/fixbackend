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
from datetime import datetime
from typing import List

from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import ForeignKey, String, DateTime
from sqlalchemy.orm import Mapped, relationship, mapped_column

from fixbackend.auth.models import User
from fixbackend.base_model import Base


class Organization(Base):
    __tablename__ = "organization"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(length=320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(length=320), nullable=False)
    external_id: Mapped[uuid.UUID] = mapped_column(GUID, default=uuid.uuid4, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID, default=uuid.uuid4, nullable=False)
    owners: Mapped[List["OrganizationOwners"]] = relationship(back_populates="organization")
    members: Mapped[List["OrganizationMembers"]] = relationship(back_populates="organization")


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
