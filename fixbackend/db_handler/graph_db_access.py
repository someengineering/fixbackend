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

from arango.client import ArangoClient
from attr import define
from fixcloudutils.arangodb.arangodb_extensions import ArangoHTTPClient
from fixcloudutils.arangodb.async_arangodb import AsyncArangoDB


@define
class GraphDatabaseAccess:
    tenant_id: str
    server: str
    username: str
    password: str
    database: str

    def client(self) -> AsyncArangoDB:
        # TODO: pass the SSL context here
        http_client = ArangoHTTPClient(60, True)
        client = ArangoClient(hosts=self.server, http_client=http_client)
        db = client.db(self.database, username=self.username, password=self.password)
        return AsyncArangoDB(db)


class GraphDatabaseAccessHolder:
    """
    This class should be used in most parts of the application.
    The tenant id should be set in the context of the request.
    """

    # TODO: This class should provide a way to get the database based on the current tenant
    def database_for_current_tenant(self) -> GraphDatabaseAccess:
        return GraphDatabaseAccess(
            tenant_id="test",
            server="http://localhost:8529",
            username="resoto",
            password="",
            database="resoto",
        )


class GraphDatabaseAccessManager:
    """
    Only wire this manager into background service classes, that manage stuff for multiple tenants.
    """

    # TODO: This class should provide a way to get the database based on the tenant id.
    def database_for_tenant(self, tenant_id: str) -> GraphDatabaseAccess:
        return GraphDatabaseAccess(
            tenant_id=tenant_id,
            server="http://localhost:8529",
            username="resoto",
            password="",
            database="resoto",
        )
