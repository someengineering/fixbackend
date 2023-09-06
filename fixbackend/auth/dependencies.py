import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.security.http import HTTPBearer
from fastapi_users import FastAPIUsers

from fixbackend.auth.jwt import jwt_auth_backend
from fixbackend.auth.models import User
from fixbackend.auth.user_manager import get_user_manager

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [jwt_auth_backend])


current_active_verified_user = fastapi_users.current_user(active=True, verified=True)


bearer_header = HTTPBearer()


class CurrentVerifyedActiveUserDependencies:
    def __init__(
        self,
        swagger_auth_workaround: Annotated[str, Depends(bearer_header)],  # to generate swagger bearer auth
        user: Annotated[User, Depends(current_active_verified_user)],
    ) -> None:
        self.user = user


AuthenticatedUser = Annotated[CurrentVerifyedActiveUserDependencies, Depends()]
