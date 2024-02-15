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


from typing import Annotated, Dict, List, Optional, override
import uuid
from abc import ABC, abstractmethod

from fastapi import Depends

from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy.ext.asyncio import AsyncSession
from fixbackend.dependencies import FixDependency, ServiceNames
from fixbackend.ids import UserRoleId, UserId, WorkspaceId
from sqlalchemy import Integer, ForeignKey, UniqueConstraint, select, update
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.permissions.models import WorkspacePermission, UserRole, RoleName, roles_to_permissions
from fixbackend.base_model import Base

from fixbackend.types import AsyncSessionMaker


class UserRoleAssignmentEntity(Base):
    __tablename__ = "user_role_assignment"

    id: Mapped[UserRoleId] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[UserId] = mapped_column(GUID, ForeignKey("user.id"), nullable=False, index=True)
    workspace_id: Mapped[WorkspaceId] = mapped_column(GUID, nullable=False, index=True)
    role_names: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "workspace_id"),)

    def to_model(self) -> UserRole:
        return UserRole(
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            role_names=RoleName(self.role_names),
        )

    @staticmethod
    def from_model(model: UserRole, id: UserRoleId) -> "UserRoleAssignmentEntity":
        return UserRoleAssignmentEntity(
            id=id,
            user_id=model.user_id,
            workspace_id=model.workspace_id,
            role_names=model.role_names.value,
        )


class RoleRepository(ABC):
    @abstractmethod
    async def list_roles(self, user_id: UserId) -> List[UserRole]:
        pass

    @abstractmethod
    async def list_roles_by_workspace_id(self, workspace_id: WorkspaceId) -> List[UserRole]:
        pass

    @abstractmethod
    async def add_roles(
        self,
        user_id: UserId,
        workspace_id: WorkspaceId,
        roles: RoleName,
        *,
        session: Optional[AsyncSession] = None,
        replace: bool = False
    ) -> UserRole:
        pass

    @abstractmethod
    async def remove_roles(
        self, user_id: UserId, workspace_id: WorkspaceId, roles: RoleName, *, session: Optional[AsyncSession] = None
    ) -> None:
        pass


class RoleRepositoryImpl(RoleRepository):

    def __init__(
        self, session_maker: AsyncSessionMaker, permissions_dict: Dict[RoleName, WorkspacePermission] | None = None
    ) -> None:
        self.session_maker = session_maker
        if permissions_dict is None:
            permissions_dict = roles_to_permissions
        self.roles_to_permissions = permissions_dict

    @override
    async def list_roles(self, user_id: UserId) -> List[UserRole]:
        async with self.session_maker() as session:
            query = select(UserRoleAssignmentEntity).filter(UserRoleAssignmentEntity.user_id == user_id)
            results = await session.execute(query)
            return [elem.to_model() for elem in results.scalars().all()]

    @override
    async def list_roles_by_workspace_id(self, workspace_id: WorkspaceId) -> List[UserRole]:
        async with self.session_maker() as session:
            query = select(UserRoleAssignmentEntity).filter(UserRoleAssignmentEntity.workspace_id == workspace_id)
            results = await session.execute(query)
            return [elem.to_model() for elem in results.scalars().all()]

    @override
    async def add_roles(
        self,
        user_id: UserId,
        workspace_id: WorkspaceId,
        roles: RoleName,
        *,
        session: Optional[AsyncSession] = None,
        replace: bool = False
    ) -> UserRole:

        async def do_tx(session: AsyncSession) -> UserRole:
            existing = (
                await session.execute(
                    select(UserRoleAssignmentEntity).where(
                        UserRoleAssignmentEntity.user_id == user_id,
                        UserRoleAssignmentEntity.workspace_id == workspace_id,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                old = existing.to_model()
                if replace:
                    new_roles = roles
                else:
                    new_roles = old.role_names | roles

                await session.execute(
                    update(UserRoleAssignmentEntity)
                    .where(UserRoleAssignmentEntity.id == existing.id)
                    .values(role_names=new_roles.value)
                )

                await session.commit()
                await session.refresh(existing)

                return existing.to_model()
            else:
                entity = UserRoleAssignmentEntity(user_id=user_id, workspace_id=workspace_id, role_names=roles.value)
                model = entity.to_model()
                session.add(entity)
                await session.commit()
                return model

        if session:
            return await do_tx(session)
        else:
            async with self.session_maker() as session:
                return await do_tx(session)

    @override
    async def remove_roles(
        self, user_id: UserId, workspace_id: WorkspaceId, roles: RoleName, *, session: Optional[AsyncSession] = None
    ) -> None:

        async def do_tx(session: AsyncSession) -> None:
            maybe_entity = (
                await session.execute(
                    select(UserRoleAssignmentEntity).filter(
                        UserRoleAssignmentEntity.user_id == user_id,
                        UserRoleAssignmentEntity.workspace_id == workspace_id,
                    )
                )
            ).scalar_one_or_none()
            if maybe_entity:
                existing = maybe_entity.to_model()
                new_names = existing.role_names & ~roles

                await session.execute(
                    update(UserRoleAssignmentEntity)
                    .where(UserRoleAssignmentEntity.id == maybe_entity.id)
                    .values(role_names=new_names.value)
                )

                await session.commit()

        if session:
            return await do_tx(session)
        else:
            async with self.session_maker() as session:
                return await do_tx(session)


def get_role_repository(fix: FixDependency) -> RoleRepository:
    return fix.service(ServiceNames.role_repository, RoleRepositoryImpl)


RoleRepositoryDependency = Annotated[RoleRepository, Depends(get_role_repository)]
