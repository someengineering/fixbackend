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
from typing import Optional
from uuid import UUID

from attrs import frozen

from fixbackend.ids import WorkspaceId, CloudAccountId


@frozen
class MeteringRecord:
    id: UUID
    workspace_id: WorkspaceId
    cloud: str
    account_id: CloudAccountId
    account_name: Optional[str]
    timestamp: datetime
    job_id: str
    task_id: str
    nr_of_resources_collected: int
    nr_of_error_messages: int
    started_at: datetime
    duration: int
