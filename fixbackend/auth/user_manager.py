import uuid
from typing import Annotated, AsyncIterator

from fastapi import Depends
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase

from fixbackend.auth.db import get_user_db
from fixbackend.auth.models import User
from fixbackend.config import get_config


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = get_config().secret
    verification_token_secret = get_config().secret


async def get_user_manager(
    user_db: Annotated[SQLAlchemyUserDatabase[User, uuid.UUID], Depends(get_user_db)]
) -> AsyncIterator[UserManager]:
    yield UserManager(user_db)


UserManagerDependency = Annotated[UserManager, Depends(get_user_manager)]
