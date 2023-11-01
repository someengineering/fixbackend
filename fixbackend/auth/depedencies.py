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
from datetime import datetime, timedelta

from fastapi import Depends, Cookie
from fastapi_users import FastAPIUsers
from starlette.requests import HTTPConnection, Request

from fixbackend.auth.auth_backend import get_auth_backend, get_session_strategy, cookie_name, FixJWTStrategy
from fixbackend.auth.models import User
from fixbackend.auth.user_manager import get_user_manager
from fixbackend.config import get_config

# todo: use dependency injection
fastapi_users = FastAPIUsers[User, UUID](get_user_manager, [get_auth_backend(get_config())])

# the value below is a dependency itself
get_current_active_user = fastapi_users.current_user(active=True, verified=True)
maybe_current_active_verified_user = fastapi_users.current_user(active=True, verified=True, optional=True)


async def get_current_active_verified_user(
    connection: HTTPConnection,  # could be either a websocket or an http request
    user: Annotated[User, Depends(get_current_active_user)],
    strategy: Annotated[FixJWTStrategy, Depends(get_session_strategy)],
    fix_auth: Annotated[Optional[str], Cookie(alias=cookie_name)],
) -> User:
    # if this is called for websocket - skip the rest
    if not isinstance(connection, Request):
        return user
    # in all possible cases if we get the authenticated user, the jwt cookie must be valid.
    if fix_auth and (token := strategy.decode_token(fix_auth)):
        # if the token is to be expired in 1 hour, we need to refresh it
        if token.get("exp", 0) < (datetime.utcnow() + timedelta(hours=1)).timestamp():
            connection.scope["refreshed_session"] = await strategy.write_token(user)

    return user


AuthenticatedUser = Annotated[User, Depends(get_current_active_verified_user)]
OptionalAuthenticatedUser = Annotated[Optional[User], Depends(maybe_current_active_verified_user)]
