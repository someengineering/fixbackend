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

from typing import Any

from fastapi_users.authentication import JWTStrategy, AuthenticationBackend, BearerTransport


from fixbackend.config import ConfigDependency

bearer_transport = BearerTransport(
    tokenUrl="/auth/jwt/login"
)  # tokenUrl is only needed for swagger and non-social login, it is no needed here.


def get_jwt_strategy(config: ConfigDependency) -> JWTStrategy[Any, Any]:
    return JWTStrategy(secret=config.secret, lifetime_seconds=3600)


# for all other authenticatino tasks
jwt_auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)
