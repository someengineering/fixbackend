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


from typing import Annotated, Dict, List, override
import uuid
from abc import ABC, abstractmethod

from attrs import frozen
from fastapi import Depends

from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy.exc import IntegrityError
from fixbackend.dependencies import FixDependency, ServiceNames
from fixbackend.ids import RoleAssignmentId, UserId
from sqlalchemy import String, ForeignKey, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.auth.models import Role, roles_dict
from fixbackend.base_model import Base

from fixbackend.types import AsyncSessionMaker


@frozen
class UserRoleAssignment:
    id: RoleAssignmentId
    user_id: UserId
    role_name: str


class UserRoleAssignmentEntity(Base):
    __tablename__ = "user_role_assignment"

    id: Mapped[RoleAssignmentId] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[UserId] = mapped_column(GUID, ForeignKey("user.id"), nullable=False, index=True)
    role_name: Mapped[str] = mapped_column(String(length=256), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "role_name"),)

    def to_model(self) -> UserRoleAssignment:
        return UserRoleAssignment(
            id=self.id,
            user_id=self.user_id,
            role_name=self.role_name,
        )

    @staticmethod
    def from_model(model: UserRoleAssignment) -> "UserRoleAssignmentEntity":
        return UserRoleAssignmentEntity(
            id=model.id,
            user_id=model.user_id,
            role_name=model.role_name,
        )


class RoleRepository(ABC):
    @abstractmethod
    async def list_roles(self, user_id: UserId) -> List[Role]:
        pass

    @abstractmethod
    async def add_role(self, user_id: UserId, role: Role) -> None:
        pass

    @abstractmethod
    async def remove_role(self, user_id: UserId, role: Role) -> None:
        pass


class RoleRepositoryImpl(RoleRepository):

    def __init__(self, session_maker: AsyncSessionMaker, roles: Dict[str, Role] | None = None) -> None:
        self.session_maker = session_maker
        if roles is None:
            roles = roles_dict
        self.roles = roles

    @override
    async def list_roles(self, user_id: UserId) -> List[Role]:
        async with self.session_maker() as session:
            query = select(UserRoleAssignmentEntity).filter(UserRoleAssignmentEntity.user_id == user_id)
            results = await session.execute(query)
            assignments = [elem.to_model() for elem in results.scalars().all()]
            return [self.roles[role.role_name] for role in assignments]

    @override
    async def add_role(self, user_id: UserId, role: Role) -> None:
        async with self.session_maker() as session:
            existing = (
                await session.execute(
                    select(UserRoleAssignmentEntity).filter(
                        UserRoleAssignmentEntity.user_id == user_id, UserRoleAssignmentEntity.role_name == role.name
                    )
                )
            ).first()
            if not existing:
                try:
                    session.add(UserRoleAssignmentEntity(user_id=user_id, role_name=role.name))
                    await session.commit()
                except IntegrityError:
                    await session.rollback()

    @override
    async def remove_role(self, user_id: UserId, role: Role) -> None:
        async with self.session_maker() as session:
            maybe_entity = (
                await session.execute(
                    select(UserRoleAssignmentEntity).filter(
                        UserRoleAssignmentEntity.user_id == user_id, UserRoleAssignmentEntity.role_name == role.name
                    )
                )
            ).scalar_one_or_none()
            if maybe_entity:
                await session.delete(maybe_entity)
                await session.commit()


def get_role_repository(fix: FixDependency) -> RoleRepository:
    return fix.service(ServiceNames.role_repository, RoleRepositoryImpl)


RoleRepositoryDependency = Annotated[RoleRepository, Depends(get_role_repository)]
