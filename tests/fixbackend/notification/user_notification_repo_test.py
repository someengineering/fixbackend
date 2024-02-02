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


import pytest

from fixbackend.notification.user_notification_repo import NotificationSettings, UserNotificationRepositoryImpl
from fixbackend.types import AsyncSessionMaker
from fixbackend.auth.models import User


@pytest.mark.asyncio
async def test_user_notification_settings_repo(async_session_maker: AsyncSessionMaker, user: User) -> None:

    repo = UserNotificationRepositoryImpl(async_session_maker)

    # default settings are always available
    settings = await repo.get_notification_settings(user.id)
    assert settings.user_id == user.id
    assert settings.weekly_report is True
    assert settings.inactivity_reminder is False

    # update settings
    updated = await repo.update_notification_settings(
        user.id, NotificationSettings(user_id=user.id, weekly_report=False, inactivity_reminder=True)
    )
    assert updated.weekly_report is False
    assert updated.inactivity_reminder is True

    # get updated settings
    settings = await repo.get_notification_settings(user.id)
    assert settings.user_id == user.id
    assert settings.weekly_report is False
    assert settings.inactivity_reminder is True
