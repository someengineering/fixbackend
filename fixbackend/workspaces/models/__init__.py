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

from datetime import datetime
from typing import List
from uuid import UUID

from attrs import frozen

from fixbackend.ids import WorkspaceId, UserId, ExternalId


@frozen
class Workspace:
    id: WorkspaceId
    slug: str
    name: str
    external_id: ExternalId
    owners: List[UserId]
    members: List[UserId]

    def all_users(self) -> List[UserId]:
        return self.owners + self.members


@frozen
class WorkspaceInvite:
    id: UUID
    workspace_id: WorkspaceId
    user_id: UserId
    expires_at: datetime