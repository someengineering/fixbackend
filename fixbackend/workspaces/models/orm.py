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
from sqlalchemy import ForeignKey, String, DateTime, Integer, func
from sqlalchemy.orm import Mapped, relationship, mapped_column

from fixbackend.auth.models import orm
from fixbackend.base_model import Base, CreatedUpdatedMixin
from fixbackend.ids import InvitationId, SubscriptionId, WorkspaceId, UserId, ExternalId, ProductTier
from fixbackend.workspaces import models
from fixbackend.permissions.models import Roles
from fixbackend.sqlalechemy_extensions import UTCDateTime


class Organization(Base, CreatedUpdatedMixin):
    __tablename__ = "organization"

    id: Mapped[WorkspaceId] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(length=320), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(length=320), nullable=False)
    external_id: Mapped[ExternalId] = mapped_column(GUID, default=uuid.uuid4, nullable=False)
    owner_id: Mapped[UserId] = mapped_column(GUID, ForeignKey("user.id"), nullable=False, index=True)
    members: Mapped[List["OrganizationMembers"]] = relationship(back_populates="organization", lazy="joined")
    tier: Mapped[str] = mapped_column(String(length=64), nullable=False, index=True, default=ProductTier.Trial.value)
    subscription_id: Mapped[Optional[SubscriptionId]] = mapped_column(GUID, nullable=True, index=True)
    payment_on_hold_since: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), index=True)

    def to_model(self) -> models.Workspace:
        return models.Workspace(
            id=self.id,
            slug=self.slug,
            name=self.name,
            external_id=self.external_id,
            owner_id=UserId(self.owner_id),
            members=[UserId(member.user_id) for member in self.members],
            product_tier=ProductTier.from_str(self.tier),
            subscription_id=self.subscription_id,
            payment_on_hold_since=self.payment_on_hold_since,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class OrganizationInvite(Base):
    __tablename__ = "organization_invite"

    id: Mapped[InvitationId] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[WorkspaceId] = mapped_column(GUID, ForeignKey("organization.id"), nullable=False)
    user_email: Mapped[str] = mapped_column(String(length=320), nullable=False, unique=False)
    role: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    version_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __mapper_args__ = {"version_id_col": version_id}  # for optimistic locking

    def to_model(self) -> models.WorkspaceInvitation:
        return models.WorkspaceInvitation(
            id=self.id,
            workspace_id=self.organization_id,
            email=self.user_email,
            role=Roles(self.role),
            expires_at=self.expires_at,
            accepted_at=self.accepted_at,
        )


# todo: remove this sometime
class OrganizationOwners(Base):
    """
    Many-to-many relationship between organizations and owners.
    """

    __tablename__ = "organization_owners"

    organization_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organization.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("user.id"), primary_key=True)


class OrganizationMembers(Base):
    """
    Many-to-many relationship between organizations and members.
    """

    __tablename__ = "organization_members"

    organization_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organization.id"), primary_key=True)
    organization: Mapped[Organization] = relationship(back_populates="members")
    user_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("user.id"), primary_key=True)
    user: Mapped[orm.User] = relationship()
