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

from typing import Annotated, AsyncIterator

from fastapi import Depends

from fixbackend.auth.db import UserRepositoryDependency
from fixbackend.auth.user_manager import UserManager
from fixbackend.auth.user_verifier import UserVerifierDependency
from fixbackend.config import ConfigDependency
from fixbackend.organizations.dependencies import OrganizationServiceDependency


async def get_user_manager(
    config: ConfigDependency,
    user_repository: UserRepositoryDependency,
    user_verifier: UserVerifierDependency,
    organization_service: OrganizationServiceDependency,
) -> AsyncIterator[UserManager]:
    yield UserManager(config, user_repository, None, user_verifier, organization_service)


UserManagerDependency = Annotated[UserManager, Depends(get_user_manager)]
