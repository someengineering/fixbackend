
from typing import Annotated
from fastapi import Depends
import uuid
from fastapi.security.http import HTTPBearer
from fixbackend.auth.models import User
from fastapi_users import FastAPIUsers
from fixbackend.auth.models import User
from fixbackend.auth.user_manager import get_user_manager
from fixbackend.auth.jwt import jwt_auth_backend

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [jwt_auth_backend])


current_active_user = fastapi_users.current_user(active=True)



bearer_header = HTTPBearer()

class CurrentActiveUserDependencies:
    def __init__(
            self, 
            swagger_auth_workaround: Annotated[str, Depends(bearer_header)], # to enable swagger bearer auth
            user: Annotated[User, Depends(current_active_user)], 
        ) -> None:
        self.user = user

UserContext = Annotated[CurrentActiveUserDependencies, Depends()]