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
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column

from fixbackend.base_model import Base, CreatedUpdatedMixin
from fixbackend.ids import WorkspaceId
from fixbackend.notification.model import WorkspaceAlert
from fixbackend.sqlalechemy_extensions import AsJsonPydantic, GUID
from fixbackend.types import AsyncSessionMaker


class WorkspaceAlertConfigEntry(Base, CreatedUpdatedMixin):
    __tablename__ = "workspace_alert_config"

    workspace_id: Mapped[WorkspaceId] = mapped_column(GUID, primary_key=True)
    alerts: Mapped[WorkspaceAlert] = mapped_column(AsJsonPydantic(WorkspaceAlert))

    def as_model(self) -> WorkspaceAlert:
        return WorkspaceAlert(workspace_id=self.workspace_id, alerts=self.alerts.alerts)

    @staticmethod
    def from_model(alert: WorkspaceAlert) -> WorkspaceAlertConfigEntry:
        return WorkspaceAlertConfigEntry(workspace_id=alert.workspace_id, alerts=alert)


class WorkspaceAlertRepository:
    def __init__(self, session_maker: AsyncSessionMaker):
        self.session_maker = session_maker

    async def alerting_for(self, workspace_id: WorkspaceId) -> Optional[WorkspaceAlert]:
        async with self.session_maker() as session:
            if result := await session.get(WorkspaceAlertConfigEntry, workspace_id):
                return result.as_model()
            else:
                return None

    async def set_alerting_for_workspace(self, alert: WorkspaceAlert) -> WorkspaceAlert:
        async with self.session_maker() as session:
            alert_entry = WorkspaceAlertConfigEntry.from_model(alert)
            await session.merge(alert_entry)
            await session.commit()
            return alert
