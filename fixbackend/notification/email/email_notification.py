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
import logging

from fixcloudutils.types import Json

from fixbackend.config import Config
from fixbackend.notification.email import email_messages
from fixbackend.notification.email.email_sender import EmailSender
from fixbackend.notification.model import (
    AlertSender,
    Alert,
    FailingBenchmarkChecksDetected,
)

log = logging.getLogger(__name__)


class EmailNotificationSender(AlertSender):
    def __init__(self, cfg: Config, email_sender: EmailSender) -> None:
        self.config = cfg
        self.sender = email_sender

    async def send_alert(self, alert: Alert, config: Json) -> None:
        if to := config.get("email"):
            match alert:
                case FailingBenchmarkChecksDetected() as vrd:
                    subject = f"{vrd.emoji()} {vrd.severity.capitalize()}: New issues Detected in your Infrastructure!"
                    text = email_messages.render("failing_benchmarks_detected.txt", alert=vrd, config=self.config)
                    html = email_messages.render("failing_benchmarks_detected.html", alert=vrd, config=self.config)
                case _:
                    raise ValueError(f"Unknown alert: {alert}")

            log.info(f"Send email notification for workspace {alert.workspace_id}")
            to = [to] if isinstance(to, str) else to
            await self.sender.send_email(to=to, subject=subject, text=text, html=html)
