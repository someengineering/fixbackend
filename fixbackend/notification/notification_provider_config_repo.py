#  Copyright (c) 2024. Some Engineering
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
from typing import Optional, Literal

from fixcloudutils.types import Json
from sqlalchemy import String, JSON, delete
from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.base_model import Base, CreatedUpdatedMixin
from fixbackend.ids import WorkspaceId
from fixbackend.sqlalechemy_extensions import GUID
from fixbackend.types import AsyncSessionMaker

NotificationProvider = Literal["slack", "discord", "pagerduty", "teams"]


class NotificationProviderConfigEntity(Base, CreatedUpdatedMixin):
    __tablename__ = "notification_provider_config"

    workspace_id: Mapped[WorkspaceId] = mapped_column(GUID, primary_key=True)
    provider: Mapped[NotificationProvider] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    messaging_config: Mapped[Json] = mapped_column(JSON)


class NotificationProviderConfigRepository:
    def __init__(self, session_maker: AsyncSessionMaker):
        self.session_maker = session_maker

    async def get_messaging_config_for_workspace(
        self, workspace_id: WorkspaceId, provider: NotificationProvider
    ) -> Optional[Json]:
        async with self.session_maker() as session:
            if result := await session.get(NotificationProviderConfigEntity, (workspace_id, provider)):
                return result.messaging_config
            else:
                return None

    async def update_messaging_config_for_workspace(
        self, workspace_id: WorkspaceId, provider: NotificationProvider, name: str, messaging_config: Json
    ) -> None:
        async with self.session_maker() as session:
            messaging_config_entity = NotificationProviderConfigEntity(
                workspace_id=workspace_id, provider=provider, name=name[0:63], messaging_config=messaging_config
            )
            await session.merge(messaging_config_entity)
            await session.commit()

    async def delete_messaging_config_for_workspace(
        self, workspace_id: WorkspaceId, provider: NotificationProvider
    ) -> None:
        async with self.session_maker() as session:
            await session.execute(
                delete(NotificationProviderConfigEntity)
                .where(NotificationProviderConfigEntity.workspace_id == workspace_id)
                .where(NotificationProviderConfigEntity.provider == provider)
            )
            await session.commit()
