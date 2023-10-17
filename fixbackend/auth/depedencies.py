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
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
from typing import Annotated, Optional
from uuid import UUID

from fastapi import Depends
from fastapi_users import FastAPIUsers

from fixbackend.auth.auth_backend import get_auth_backend, get_aws_marketplace_auth_backend
from fixbackend.auth.models import User
from fixbackend.auth.user_manager import get_user_manager
from fixbackend.config import get_config
from fastapi_users.authentication import Authenticator


# todo: use dependency injection
fastapi_users = FastAPIUsers[User, UUID](get_user_manager, [get_auth_backend(get_config())])
aws_marketplace_authenticator = Authenticator([get_aws_marketplace_auth_backend(get_config())], get_user_manager)

# the value below is a dependency itself
get_current_active_verified_user = fastapi_users.current_user(active=True, verified=True)

# Not CSRF-safe! Use only for aws marketplace callbacks
maybe_current_active_verified_user = aws_marketplace_authenticator.current_user(
    active=True, verified=True, optional=True
)


AuthenticatedUser = Annotated[User, Depends(get_current_active_verified_user)]
OptionalAuthenticatedUser = Annotated[Optional[User], Depends(maybe_current_active_verified_user)]
