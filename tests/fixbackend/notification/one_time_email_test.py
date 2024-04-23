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

from datetime import timedelta

from fixcloudutils.util import utc

from fixbackend.auth.user_repository import UserRepository
from fixbackend.auth.models import User
from fixbackend.notification.email.email_messages import TrialExpired
from fixbackend.notification.email.one_time_email import OneTimeEmailKind, OneTimeEmailService
from fixbackend.notification.notification_service import NotificationService
from fixbackend.types import AsyncSessionMaker
from tests.fixbackend.conftest import InMemoryEmailSender


async def test_schedule_one_time_email(
    notification_service: NotificationService,
    user_repository: UserRepository,
    async_session_maker: AsyncSessionMaker,
    user: User,
    email_sender: InMemoryEmailSender,
) -> None:

    one_time_sender = OneTimeEmailService(notification_service, user_repository, async_session_maker, dispatching=False)

    message = TrialExpired()

    await one_time_sender.schedule_one_time_email(
        kind=OneTimeEmailKind.TrialEndNotification,
        scheduled_at=utc() - timedelta(days=1),
        user_id=user.id,
        workspace_id=None,
        message=message,
    )

    await one_time_sender.schedule_one_time_email(
        kind=OneTimeEmailKind.TrialEndNotification,
        scheduled_at=utc() + timedelta(days=1),
        user_id=user.id,
        workspace_id=None,
        message=message,
    )

    pending = await one_time_sender.list_pending_emails()
    assert len(pending) == 1

    assert len(email_sender.call_args) == 0

    await one_time_sender._send_emails_job()

    pending = await one_time_sender.list_pending_emails()
    assert len(pending) == 0

    assert len(email_sender.call_args) == 1


async def test_unschedule_one_time_email(
    notification_service: NotificationService,
    user_repository: UserRepository,
    async_session_maker: AsyncSessionMaker,
    user: User,
    email_sender: InMemoryEmailSender,
) -> None:

    one_time_sender = OneTimeEmailService(notification_service, user_repository, async_session_maker, dispatching=False)

    message = TrialExpired()

    await one_time_sender.schedule_one_time_email(
        kind=OneTimeEmailKind.TrialEndNotification,
        scheduled_at=utc() - timedelta(days=1),
        user_id=user.id,
        workspace_id=None,
        message=message,
    )

    await one_time_sender.schedule_one_time_email(
        kind=OneTimeEmailKind.TrialEndNotification,
        scheduled_at=utc() + timedelta(days=1),
        user_id=user.id,
        workspace_id=None,
        message=message,
    )

    pending = await one_time_sender.list_pending_emails()
    assert len(pending) == 1

    assert len(email_sender.call_args) == 0

    await one_time_sender.unschedule_one_time_email(
        user_id=user.id, workspace_id=None, kind=OneTimeEmailKind.TrialEndNotification
    )

    pending = await one_time_sender.list_pending_emails()
    assert len(pending) == 0

    await one_time_sender._send_emails_job()

    assert len(email_sender.call_args) == 0
