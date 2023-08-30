
from typing import Annotated
from fastapi import Depends
from fastapi.security.http import HTTPBearer
from fixbackend.auth.users import fastapi_users
from fixbackend.auth.models import User


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