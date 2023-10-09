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
import uuid

import pytest

from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import WorkspaceId
from fixbackend.types import AsyncSessionMaker


@pytest.mark.asyncio
async def test_access_manager(graph_database_access_manager: GraphDatabaseAccessManager) -> None:
    workspace_id = WorkspaceId(uuid.uuid4())
    access = await graph_database_access_manager.create_database_access(workspace_id)
    again = await graph_database_access_manager.get_database_access(workspace_id)
    assert access == again


@pytest.mark.asyncio
async def test_access_manager_join_session(
    graph_database_access_manager: GraphDatabaseAccessManager, async_session_maker: AsyncSessionMaker
) -> None:
    workspace_id = WorkspaceId(uuid.uuid4())
    async with async_session_maker() as session:
        res = await graph_database_access_manager.create_database_access(workspace_id, session=session)
        assert res is not None
        # rolling back the session should also roll back the database access
        await session.rollback()
        assert await graph_database_access_manager.get_database_access(workspace_id) is None
