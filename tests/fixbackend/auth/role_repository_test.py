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


import pytest

from fixbackend.auth.models import Roles, User
from fixbackend.auth.role_repository import RoleRepositoryImpl

from fixbackend.types import AsyncSessionMaker


@pytest.mark.asyncio
async def test_role_repository(async_session_maker: AsyncSessionMaker, user: User) -> None:

    role_repository = RoleRepositoryImpl(session_maker=async_session_maker)

    assert await role_repository.list_roles(user.id) == []

    await role_repository.add_role(user.id, Roles.workspace_member)

    assert await role_repository.list_roles(user.id) == [Roles.workspace_member]

    await role_repository.add_role(user.id, Roles.workspace_admin)

    assert set(map(lambda r: r.name, await role_repository.list_roles(user.id))) == set(
        [Roles.workspace_member.name, Roles.workspace_admin.name]
    )

    await role_repository.remove_role(user.id, Roles.workspace_member)

    assert await role_repository.list_roles(user.id) == [Roles.workspace_admin]
