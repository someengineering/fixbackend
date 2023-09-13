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

from typing import Annotated, AsyncIterator
from fastapi import Depends
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from fixbackend.db import get_async_session
from sqlalchemy.ext.asyncio import AsyncSession
from fixbackend.auth.models import User, OAuthAccount


async def get_user_db(
    session: Annotated[AsyncSession, Depends(get_async_session)]
) -> AsyncIterator[SQLAlchemyUserDatabase[User, OAuthAccount]]:
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)
