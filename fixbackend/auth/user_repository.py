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

from typing import Annotated, Any, AsyncIterator, Dict, List, Optional
from uuid import UUID

from fastapi import Depends
from fastapi_users.db.base import BaseUserDatabase
from fastapi_users.password import PasswordHelperProtocol
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.auth.models import OAuthAccount, User, orm
from fixbackend.db import AsyncSessionMakerDependency
from fixbackend.ids import UserId
from fixbackend.types import AsyncSessionMaker
from contextlib import asynccontextmanager
from fastapi_users.exceptions import UserAlreadyExists


class UserRepository(BaseUserDatabase[User, UserId]):
    def __init__(
        self,
        session_maker: AsyncSessionMaker,
    ) -> None:
        self.session_maker = session_maker

    @asynccontextmanager
    async def user_db(
        self, session: Optional[AsyncSession] = None
    ) -> AsyncIterator[SQLAlchemyUserDatabase[orm.User, GUID]]:
        if session:
            yield SQLAlchemyUserDatabase(session, orm.User, orm.OAuthAccount)
        else:
            async with self.session_maker() as session:
                yield SQLAlchemyUserDatabase(session, orm.User, orm.OAuthAccount)

    async def get(self, id: UserId) -> Optional[User]:
        """Get a single user by id."""
        async with self.user_db() as db:
            user = await db.get(id)  # type: ignore[arg-type]
            return user.to_model() if user else None

    async def get_by_email(self, email: str, *, session: Optional[AsyncSession] = None) -> Optional[User]:
        """Get a single user by email."""
        async with self.user_db(session) as db:
            user = await db.get_by_email(email)
            return user.to_model() if user else None

    async def get_by_ids(self, ids: List[UserId]) -> List[User]:
        """Get a list of users by ids."""
        async with self.user_db() as db:
            result = await db.session.execute(select(orm.User).filter(orm.User.id.in_(ids)))  # type: ignore
            users = result.unique().scalars().all()

            return [user.to_model() for user in users]

    async def get_by_oauth_account(self, oauth: str, account_id: str) -> Optional[User]:
        """Get a single user by OAuth account id."""
        async with self.user_db() as db:
            user = await db.get_by_oauth_account(oauth, account_id)
            return user.to_model() if user else None

    async def create(self, create_dict: Dict[str, Any]) -> User:
        """Create a user."""
        async with self.user_db() as db:
            user = await db.create(create_dict)
            return user.to_model()

    async def update(self, user: User, update_dict: Dict[str, Any]) -> User:
        """Update a user."""

        # copied from fastapi_users_db_sqlalchemy due to its
        # inflexibility

        async with self.user_db() as db:
            orm_user = await db.session.get(orm.User, user.id)
            if orm_user is None:
                raise ValueError(f"User {user.id} not found")
            for key, value in update_dict.items():
                setattr(orm_user, key, value)
            db.session.add(orm_user)
            await db.session.commit()
            await db.session.refresh(orm_user)
            return orm_user.to_model()

    async def delete(self, user: User) -> None:
        """Delete a user."""

        async with self.user_db() as db:
            await db.delete(orm.User.from_model(user))

    async def add_oauth_account(self, user: User, create_dict: Dict[str, Any]) -> User:
        """Create an OAuth account and add it to the user."""

        async with self.user_db() as db:

            orm_user = await db.session.get(orm.User, user.id)
            if orm_user is None:
                raise ValueError(f"User {user.id} not found")
            existing_account_query_result = await db.session.execute(
                select(orm.OAuthAccount).where(orm.OAuthAccount.account_id == create_dict["account_id"])
            )
            existing_account = existing_account_query_result.scalar_one_or_none()
            if existing_account:
                if existing_account.user_id != user.id:
                    # this oauth account is already linked to another user, do not let this happen
                    raise UserAlreadyExists(f"Account {create_dict['account_id']} already linked to another user")

            oauth_account = orm.OAuthAccount(**create_dict)
            db.session.add(oauth_account)

            if existing_account:
                # remove the old oauth association
                await db.session.delete(existing_account)

            orm_user.oauth_accounts.append(oauth_account)
            db.session.add(orm_user)
            await db.session.commit()
            await db.session.refresh(orm_user)

            return orm_user.to_model()

    async def update_oauth_account(
        self,
        user: User,
        oauth_account: OAuthAccount,  # type: ignore[override]
        update_dict: Dict[str, Any],
    ) -> User:
        """Update an OAuth account on a user."""

        async with self.user_db() as db:
            orm_user = await db.session.get(orm.User, user.id)
            orm_oauth_account = await db.session.get(orm.OAuthAccount, oauth_account.id)

            for key, value in update_dict.items():
                setattr(orm_oauth_account, key, value)
            db.session.add(orm_oauth_account)
            await db.session.commit()
            await db.session.refresh(orm_user)
            if orm_user is None:
                raise ValueError(f"User {user.id} not found")

            return orm_user.to_model()

    async def remove_oauth_account(self, account_id: UUID) -> None:
        """Remove an OAuth account from a user."""
        async with self.user_db() as db:
            orm_oauth_account = await db.session.get(orm.OAuthAccount, account_id)
            if orm_oauth_account is None:
                return None
            await db.session.delete(orm_oauth_account)
            await db.session.commit()

    async def recreate_otp_secret(
        self, user_id: UserId, otp_secret: str, is_mfa_active: bool, hashes: List[str]
    ) -> None:
        """Put recovery codes for a user."""
        async with self.user_db() as db:
            orm_user = await db.session.get(orm.User, user_id)
            if orm_user is None:
                raise ValueError(f"User {user_id} not found")
            # delete all existing recovery codes of this user
            orm_user.mfa_recovery_codes.clear()
            orm_user.otp_secret = otp_secret
            orm_user.is_mfa_active = is_mfa_active
            # add the new recovery codes
            for code_hash in hashes:
                recovery_code = orm.UserMFARecoveryCode(user_id=user_id, code_hash=code_hash)
                db.session.add(recovery_code)
            await db.session.commit()

    async def delete_recovery_code(self, user_id: UserId, code: str, pw_help: PasswordHelperProtocol) -> bool:
        """Delete a specific recovery code for a user and return whether it existed."""
        async with self.user_db() as db:
            # Fetch the recovery codes
            result = await db.session.execute(
                select(orm.UserMFARecoveryCode).where(orm.UserMFARecoveryCode.user_id == user_id)
            )
            recovery_codes = result.scalars().all()
        # Check each recovery code
        for recovery_code in recovery_codes:
            if pw_help.verify_and_update(code, recovery_code.code_hash):
                # If the recovery code matches, delete it and return True
                await db.session.delete(recovery_code)
                await db.session.commit()
                return True
        return False


async def get_user_repository(session_maker: AsyncSessionMakerDependency) -> AsyncIterator[UserRepository]:
    yield UserRepository(session_maker)


UserRepositoryDependency = Annotated[UserRepository, Depends(get_user_repository)]
