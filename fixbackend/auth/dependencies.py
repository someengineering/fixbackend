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
