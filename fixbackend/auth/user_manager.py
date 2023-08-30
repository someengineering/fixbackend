import uuid
from typing import Annotated

from fastapi import Depends
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users.db import SQLAlchemyUserDatabase

from fixbackend.auth.db import get_user_db
from fixbackend.config import get_config
from fixbackend.auth.models import User



class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = get_config().secret
    verification_token_secret = get_config().secret


async def get_user_manager(user_db: Annotated[SQLAlchemyUserDatabase, Depends(get_user_db)]):
    yield UserManager(user_db)

