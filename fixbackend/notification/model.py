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
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
from typing import Dict, List, Literal

from pydantic import BaseModel, Field

from fixbackend.ids import WorkspaceId
from fixbackend.inventory.inventory_service import ReportSeverity

Channel = Literal["email", "slack", "discord", "pagerduty", "teams"]
AllowedChannels = {"email", "slack", "discord", "pagerduty", "teams"}


class AlertingSetting(BaseModel):
    severity: ReportSeverity = Field(
        default="critical",
        description="Minimum severity to send alerts for. Example: high will send alerts for high and critical",
    )
    channels: List[Channel] = Field(default_factory=list, description="List of channels to send alerts to")


class WorkspaceAlert(BaseModel):
    workspace_id: WorkspaceId
    # benchmark name -> AlertingSetting
    alerts: Dict[str, AlertingSetting] = {}

    def non_empty_alerts(self) -> Dict[str, AlertingSetting]:
        return {k: v for k, v in self.alerts.items() if v.channels}
