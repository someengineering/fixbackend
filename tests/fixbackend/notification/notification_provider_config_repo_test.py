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

from fixbackend.ids import WorkspaceId
from fixbackend.notification.notification_provider_config_repo import NotificationProviderConfigRepository
from fixbackend.types import AsyncSessionMaker
from fixbackend.utils import uid


@pytest.mark.asyncio
async def test_notification_provider_config_repo(async_session_maker: AsyncSessionMaker) -> None:
    repo = NotificationProviderConfigRepository(async_session_maker)
    ws1 = WorkspaceId(uid())
    cfg = {"url": "https://slack.com"}
    cfg2 = {"url": "https://slack.com", "token": "abc"}
    # insert
    await repo.update_messaging_config_for_workspace(ws1, "slack", cfg)
    assert await repo.get_messaging_config_for_workspace(ws1, "slack") == cfg
    # update
    await repo.update_messaging_config_for_workspace(ws1, "slack", cfg2)
    assert await repo.get_messaging_config_for_workspace(ws1, "slack") == cfg2
    # delete
    await repo.delete_messaging_config_for_workspace(ws1, "slack")
    assert await repo.get_messaging_config_for_workspace(ws1, "slack") is None
