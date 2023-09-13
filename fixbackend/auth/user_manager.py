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
from typing import Annotated, AsyncIterator, Optional

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users.db import BaseUserDatabase
from fastapi_users.password import PasswordHelperProtocol
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase

from fixbackend.auth.db import get_user_db
from fixbackend.auth.models import User
from fixbackend.config import get_config
from fixbackend.auth.user_verifyer import UserVerifyerDependency, UserVerifyer


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = get_config().secret
    verification_token_secret = get_config().secret

    def __init__(
        self,
        user_db: BaseUserDatabase[User, uuid.UUID],
        password_helper: PasswordHelperProtocol | None,
        user_verifyer: UserVerifyer,
    ):
        super().__init__(user_db, password_helper)
        self.user_verifyer = user_verifyer

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        if not user.is_verified:  # oauth2 users are already verifyed
            await self.request_verify(user, request)

    async def on_after_request_verify(self, user: User, token: str, request: Optional[Request] = None) -> None:
        await self.user_verifyer.verify(user, token)


async def get_user_manager(
    user_db: Annotated[SQLAlchemyUserDatabase[User, uuid.UUID], Depends(get_user_db)],
    user_verifyer: UserVerifyerDependency,
) -> AsyncIterator[UserManager]:
    yield UserManager(user_db, None, user_verifyer)


UserManagerDependency = Annotated[UserManager, Depends(get_user_manager)]
