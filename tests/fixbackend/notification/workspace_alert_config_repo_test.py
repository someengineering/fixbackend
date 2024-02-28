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
import pytest

from fixbackend.ids import NotificationProvider, WorkspaceId, BenchmarkName
from fixbackend.notification.model import WorkspaceAlert, AlertingSetting
from fixbackend.notification.workspace_alert_config_repo import WorkspaceAlertRepository
from fixbackend.types import AsyncSessionMaker
from fixbackend.utils import uid


@pytest.mark.asyncio
async def test_alerting_rule_repo(async_session_maker: AsyncSessionMaker) -> None:
    repo = WorkspaceAlertRepository(async_session_maker)
    ws1 = WorkspaceId(uid())
    alert = await repo.alerting_for(ws1)
    assert alert is None
    slack = AlertingSetting(severity="info", channels=[NotificationProvider.slack])
    pd = AlertingSetting(severity="critical", channels=[NotificationProvider.pagerduty])
    a = BenchmarkName("a")
    b = BenchmarkName("b")
    c = BenchmarkName("c")
    # insert
    alert_cfg = await repo.set_alerting_for_workspace(WorkspaceAlert(workspace_id=ws1, alerts={a: pd, b: slack}))
    assert await repo.alerting_for(ws1) == alert_cfg
    # update
    alert_cfg = await repo.set_alerting_for_workspace(WorkspaceAlert(workspace_id=ws1, alerts={c: pd}))
    assert await repo.alerting_for(ws1) == alert_cfg
