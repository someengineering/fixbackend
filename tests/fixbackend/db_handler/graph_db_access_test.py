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
from fixbackend.db_handler.graph_db_access import GraphDatabaseAccessHolder, GraphDatabaseAccessManager


def test_access_holder(graph_database_access_holder: GraphDatabaseAccessHolder) -> None:
    access = graph_database_access_holder.database_for_current_tenant()
    assert access.tenant_id == "test"


def test_access_manager(graph_database_access_manager: GraphDatabaseAccessManager) -> None:
    access = graph_database_access_manager.database_for_tenant("test")
    assert access.tenant_id == "test"
