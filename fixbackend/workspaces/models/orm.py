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
from typing import List, Optional

from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import ForeignKey, String, DateTime, Integer
from sqlalchemy.orm import Mapped, relationship, mapped_column

from fixbackend.auth.models import orm
from fixbackend.base_model import Base
from fixbackend.ids import InvitationId, WorkspaceId, UserId, ExternalId, ProductTier
from fixbackend.workspaces import models


class Organization(Base):
    __tablename__ = "organization"

    id: Mapped[WorkspaceId] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(length=320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(length=320), nullable=False)
    external_id: Mapped[ExternalId] = mapped_column(GUID, default=uuid.uuid4, nullable=False)
    owners: Mapped[List["OrganizationOwners"]] = relationship(back_populates="organization", lazy="joined")
    members: Mapped[List["OrganizationMembers"]] = relationship(back_populates="organization", lazy="joined")
    security_tier: Mapped[str] = mapped_column(String(length=64), nullable=False)

    def to_model(self) -> models.Workspace:
        return models.Workspace(
            id=self.id,
            slug=self.slug,
            name=self.name,
            external_id=self.external_id,
            owners=[UserId(owner.user_id) for owner in self.owners],
            members=[UserId(member.user_id) for member in self.members],
            product_tier=ProductTier(self.security_tier),
        )


class OrganizationInvite(Base):
    __tablename__ = "organization_invite"

    id: Mapped[InvitationId] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[WorkspaceId] = mapped_column(GUID, ForeignKey("organization.id"), nullable=False)
    user_email: Mapped[str] = mapped_column(String(length=320), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    version_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __mapper_args__ = {"version_id_col": version_id}  # for optimistic locking

    def to_model(self) -> models.WorkspaceInvitation:
        return models.WorkspaceInvitation(
            id=self.id,
            workspace_id=self.organization_id,
            email=self.user_email,
            expires_at=self.expires_at,
            accepted_at=self.accepted_at,
        )


class OrganizationOwners(Base):
    """
    Many-to-many relationship between organizations and owners.
    """

    __tablename__ = "organization_owners"

    organization_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organization.id"), primary_key=True)
    organization: Mapped[Organization] = relationship(back_populates="owners")
    user_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("user.id"), primary_key=True)
    user: Mapped[orm.User] = relationship()


class OrganizationMembers(Base):
    """
    Many-to-many relationship between organizations and members.
    """

    __tablename__ = "organization_members"

    organization_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organization.id"), primary_key=True)
    organization: Mapped[Organization] = relationship(back_populates="members")
    user_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("user.id"), primary_key=True)
    user: Mapped[orm.User] = relationship()
