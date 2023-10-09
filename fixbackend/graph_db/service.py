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
import hashlib
import logging
import secrets
import string
from typing import Optional

from fastapi_users_db_sqlalchemy.generics import GUID
from fixcloudutils.service import Service
from sqlalchemy import String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.base_model import Base
from fixbackend.config import Config
from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.ids import WorkspaceId
from fixbackend.types import AsyncSessionMaker

log = logging.getLogger(__name__)
PasswordLength = 20


class GraphDatabaseAccessEntity(Base):
    __tablename__ = "graph_database_access"
    tenant_id: Mapped[WorkspaceId] = mapped_column(GUID, primary_key=True)
    server: Mapped[str] = mapped_column(String(length=256), nullable=False)
    username: Mapped[str] = mapped_column(String(length=36), nullable=False)
    password: Mapped[str] = mapped_column(String(length=PasswordLength), nullable=False)
    database: Mapped[str] = mapped_column(String(length=40), nullable=False)

    def access(self) -> GraphDatabaseAccess:
        return GraphDatabaseAccess(
            workspace_id=self.tenant_id,
            server=self.server,
            username=self.username,
            password=self.password,
            database=self.database,
        )


class GraphDatabaseAccessManager(Service):
    def __init__(self, config: Config, session_maker: AsyncSessionMaker) -> None:
        self.config = config
        self.session_maker = session_maker

    async def create_database_access(
        self, workspace_id: WorkspaceId, *, session: Optional[AsyncSession] = None
    ) -> GraphDatabaseAccess:
        """
        Create a new database-access for the given tenant.

        :param workspace_id: The id of the tenant.
        :param session: The optional session object to join an existing transaction.
        :return: The database access.
        """

        log.info(f"Create new database access for tenant {workspace_id}")
        db_access_entity = GraphDatabaseAccessEntity(
            tenant_id=workspace_id,
            server=self._database_for(workspace_id),
            username=str(workspace_id),
            password=self._generate_password(PasswordLength),
            database=f"db-{workspace_id}",  # name needs to start with a letter!
        )
        db_access = db_access_entity.access()

        if session is not None:
            session.add(db_access_entity)
        else:
            async with self.session_maker() as session:
                session.add(db_access_entity)
                await session.commit()
        return db_access

    async def get_database_access(self, workspace_id: WorkspaceId) -> Optional[GraphDatabaseAccess]:
        async with self.session_maker() as session:
            if entity := await session.get(GraphDatabaseAccessEntity, workspace_id):
                return entity.access()
            return None

    def _database_for(self, workspace_id: WorkspaceId) -> str:
        # use consistent hashing to select a server from the list of available servers
        hashed_key = int(hashlib.sha256(str(workspace_id).encode()).hexdigest(), 16)
        return self.config.available_db_server[hashed_key % len(self.config.available_db_server)]

    def _generate_password(self, length: int) -> str:
        alphabet = string.ascii_letters + string.digits + string.punctuation
        return "".join(secrets.choice(alphabet) for _ in range(length))
