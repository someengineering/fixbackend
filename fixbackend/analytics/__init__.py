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
from abc import ABC, abstractmethod
from fixcloudutils.service import Service
from fixbackend.analytics.events import AnalyticsEvent
from fixbackend.ids import UserId, WorkspaceId


class AnalyticsEventSender(Service, ABC):
    @abstractmethod
    async def send(self, event: AnalyticsEvent) -> None:
        pass

    @abstractmethod
    async def user_id_from_workspace(self, workspace_id: WorkspaceId) -> UserId:
        pass
