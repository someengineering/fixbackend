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
#  along with this program.  If not, see <http://www.gnu.org/licenses/>

from pydantic import BaseModel, Field
from fixbackend.ids import UserId
from fixbackend.notification.user_notification_repo import NotificationSettings as NotificationSettingsModel


class NotificationSettings(BaseModel):
    weekly_report: bool = Field(description="Whether to send a weekly report")
    inactivity_reminder: bool = Field(description="Whether to send a reminder for open incidents")

    @staticmethod
    def from_model(model: NotificationSettingsModel) -> "NotificationSettings":
        return NotificationSettings(
            weekly_report=model.weekly_report,
            inactivity_reminder=model.inactivity_reminder,
        )

    def to_model(self, user_id: UserId) -> NotificationSettingsModel:
        return NotificationSettingsModel(
            user_id=user_id,
            weekly_report=self.weekly_report,
            inactivity_reminder=self.inactivity_reminder,
        )
