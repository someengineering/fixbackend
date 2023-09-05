from typing import Annotated, AsyncIterator
from fastapi import Depends
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from fixbackend.db import get_async_session
from sqlalchemy.ext.asyncio import AsyncSession
from fixbackend.auth.models import User, OAuthAccount


async def get_user_db(session: Annotated[AsyncSession, Depends(get_async_session)]) -> AsyncIterator[SQLAlchemyUserDatabase[User, OAuthAccount]]:
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)
