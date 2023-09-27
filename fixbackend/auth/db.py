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

from typing import Annotated, Any, AsyncIterator, Dict, Optional
from uuid import UUID

from fastapi import Depends
from fastapi_users.db.base import BaseUserDatabase
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.auth.models import OAuthAccount, User, orm
from fixbackend.db import AsyncSessionDependency


class UserRepository(BaseUserDatabase[User, UUID]):
    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self.db: SQLAlchemyUserDatabase[orm.User, GUID] = SQLAlchemyUserDatabase(session, orm.User, orm.OAuthAccount)

    async def get(self, id: UUID) -> Optional[User]:
        """Get a single user by id."""
        user = await self.db.get(id)  # type: ignore[arg-type]
        return User.from_orm(user) if user else None

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get a single user by email."""
        user = await self.db.get_by_email(email)
        return User.from_orm(user) if user else None

    async def get_by_oauth_account(self, oauth: str, account_id: str) -> Optional[User]:
        """Get a single user by OAuth account id."""
        user = await self.db.get_by_oauth_account(oauth, account_id)
        return User.from_orm(user) if user else None

    async def create(self, create_dict: Dict[str, Any]) -> User:
        """Create a user."""
        user = await self.db.create(create_dict)
        return User.from_orm(user)

    async def update(self, user: User, update_dict: Dict[str, Any]) -> User:
        """Update a user."""

        # copied from fastapi_users_db_sqlalchemy due to its
        # inflexibility
        orm_user = await self.db.session.get(orm.User, user.id)
        if orm_user is None:
            raise ValueError(f"User {user.id} not found")
        for key, value in update_dict.items():
            setattr(orm_user, key, value)
        self.db.session.add(orm_user)
        await self.db.session.commit()
        await self.db.session.refresh(orm_user)
        return User.from_orm(orm_user)

    async def delete(self, user: User) -> None:
        """Delete a user."""
        await self.db.delete(user.to_orm())

    async def add_oauth_account(self, user: User, create_dict: Dict[str, Any]) -> User:
        """Create an OAuth account and add it to the user."""

        if self.db.oauth_account_table is None:
            raise NotImplementedError()

        orm_user = await self.db.session.get(orm.User, user.id)
        if orm_user is None:
            raise ValueError(f"User {user.id} not found")
        oauth_account = self.db.oauth_account_table(**create_dict)
        self.db.session.add(oauth_account)
        orm_user.oauth_accounts.append(oauth_account)  # type: ignore
        self.db.session.add(orm_user)
        await self.db.session.commit()
        await self.db.session.refresh(orm_user)

        return User.from_orm(orm_user)

    async def update_oauth_account(
        self,
        user: User,
        oauth_account: OAuthAccount,  # type: ignore[override]
        update_dict: Dict[str, Any],
    ) -> User:
        """Update an OAuth account on a user."""

        orm_user = await self.db.session.get(orm.User, user.id)
        orm_oauth_account = await self.db.session.get(orm.OAuthAccount, oauth_account.id)

        for key, value in update_dict.items():
            setattr(orm_oauth_account, key, value)
        self.db.session.add(orm_oauth_account)
        await self.db.session.commit()
        await self.db.session.refresh(orm_user)
        if orm_user is None:
            raise ValueError(f"User {user.id} not found")

        return User.from_orm(orm_user)


async def get_user_repository(session: AsyncSessionDependency) -> AsyncIterator[UserRepository]:
    yield UserRepository(session)


UserRepositoryDependency = Annotated[UserRepository, Depends(get_user_repository)]
