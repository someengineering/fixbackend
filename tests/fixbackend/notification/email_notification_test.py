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

from fixbackend.notification.email.email_notification import EmailNotificationSender
from fixbackend.notification.model import FailingBenchmarkChecksDetected
from tests.fixbackend.conftest import InMemoryEmailSender


@pytest.fixture
def email_notification(email_sender: InMemoryEmailSender) -> EmailNotificationSender:
    return EmailNotificationSender(email_sender)


async def test_teams_notification(
    email_notification: EmailNotificationSender,
    alert_failing_benchmark_checks_detected: FailingBenchmarkChecksDetected,
    email_sender: InMemoryEmailSender,
) -> None:
    # sending should not fail
    await email_notification.send_alert(alert_failing_benchmark_checks_detected, dict(email="user@example.com"))
    # evaluate message
    assert len(email_sender.call_args) == 1
    email = email_sender.call_args[0]
    assert email.to == "user@example.com"
    assert email.subject == "💥 Critical: New issues Detected in your Infrastructure!"
    assert "We have completed a comprehensive scan of your infrastructure." in email.text
    assert email.html and "We have completed a comprehensive scan of your infrastructure." in email.html
