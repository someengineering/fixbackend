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
from abc import ABC, abstractmethod
from typing import Dict, List, Literal, Optional
from urllib.parse import urlencode

from attr import frozen
from pydantic import BaseModel, Field

from fixbackend.ids import WorkspaceId
from fixbackend.inventory.inventory_service import ReportSeverity
from fixcloudutils.types import Json

NotificationProvider = Literal["email", "slack", "discord", "pagerduty", "teams"]
AllowedNotificationProvider = {"email", "slack", "discord", "pagerduty", "teams"}


class AlertingSetting(BaseModel):
    severity: ReportSeverity = Field(
        default="critical",
        description="Minimum severity to send alerts for. Example: high will send alerts for high and critical",
    )
    channels: List[NotificationProvider] = Field(default_factory=list, description="List of channels to send alerts to")


class WorkspaceAlert(BaseModel):
    workspace_id: WorkspaceId
    # benchmark name -> AlertingSetting
    alerts: Dict[str, AlertingSetting] = {}

    def non_empty_alerts(self) -> Dict[str, AlertingSetting]:
        return {k: v for k, v in self.alerts.items() if v.channels}


@frozen
class Alert:
    workspace_id: WorkspaceId


@frozen
class AlertOnChannel:
    alert: Alert
    channel: NotificationProvider


@frozen
class VulnerableResource:
    id: str
    kind: str
    name: Optional[str] = None
    cloud: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    zone: Optional[str] = None

    def ui_link(self, base_url: str) -> str:
        return f"{base_url}/inventory/resource-detail/{self.id}?{urlencode(dict(name=self.name))}"


@frozen
class FailedBenchmarkCheck:
    check_id: str
    title: str
    severity: str
    failed_resources: int
    examples: List[VulnerableResource]


@frozen
class FailingBenchmarkChecksDetected(Alert):
    benchmark: str
    severity: str
    failed_checks_count_total: int
    examples: List[FailedBenchmarkCheck]
    link: str


class AlertSender(ABC):
    @abstractmethod
    async def send_alert(self, alert: Alert, config: Json) -> None:
        pass
