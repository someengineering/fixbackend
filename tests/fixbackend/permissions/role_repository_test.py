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
import pytest

from fixbackend.auth.models import User
from fixbackend.permissions.models import Roles
from fixbackend.permissions.role_repository import RoleRepository
from fixbackend.ids import WorkspaceId
from fixbackend.workspaces.models import Workspace

from fixbackend.types import AsyncSessionMaker


@pytest.mark.asyncio
async def test_role_repository(async_session_maker: AsyncSessionMaker, user: User, workspace: Workspace) -> None:

    role_repository = RoleRepository(session_maker=async_session_maker)

    workspace_id_2 = WorkspaceId(uuid.uuid4())

    # owner by default
    assert (await role_repository.list_roles(user.id))[0].role_names == Roles.workspace_owner

    # adding roles works
    await role_repository.add_roles(user.id, workspace.id, Roles.workspace_member)
    roles = await role_repository.list_roles(user.id)
    assert len(roles) == 1
    assert roles[0].role_names == Roles.workspace_member | Roles.workspace_owner

    # adding roles twice is idempotent
    await role_repository.add_roles(user.id, workspace.id, Roles.workspace_member)
    roles = await role_repository.list_roles(user.id)
    assert len(roles) == 1
    assert roles[0].role_names == Roles.workspace_member | Roles.workspace_owner

    # adding multiple roles works
    await role_repository.add_roles(user.id, workspace.id, Roles.workspace_admin)
    roles = await role_repository.list_roles(user.id)
    assert len(roles) == 1
    assert roles[0].role_names == Roles.workspace_admin | Roles.workspace_member | Roles.workspace_owner

    # removing roles works
    await role_repository.remove_roles(user.id, workspace.id, Roles.workspace_member)
    roles = await role_repository.list_roles(user.id)
    assert len(roles) == 1
    assert roles[0].role_names == Roles.workspace_admin | Roles.workspace_owner

    # adding roles for different workspaces works
    await role_repository.add_roles(user.id, workspace_id_2, Roles.workspace_admin)
    roles = await role_repository.list_roles(user.id)
    assert len(roles) == 2
    assert list(filter(lambda r: r.workspace_id != workspace.id, roles))[0].role_names == Roles.workspace_admin

    # removing roles works for different workspaces
    await role_repository.remove_roles(user.id, workspace_id_2, Roles.workspace_admin)
    roles = await role_repository.list_roles(user.id)
    assert len(roles) == 2
    assert {role.workspace_id: role.role_names for role in roles} == {
        workspace.id: Roles.workspace_admin | Roles.workspace_owner,
        workspace_id_2: Roles(0),
    }
