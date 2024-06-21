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
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.


from datetime import timedelta, datetime
import logging

from fixcloudutils.service import Service

from fixbackend.config import trial_period_duration
from fixbackend.domain_events.events import ProductTierChanged, UserRegistered, WorkspaceCreated
from fixbackend.domain_events.subscriber import DomainEventSubscriber
from fixbackend.ids import ProductTier, WorkspaceId
from fixbackend.notification.email.email_messages import Signup, TrialExpired, TrialExpiresSoon
from fixbackend.notification.email.one_time_email import OneTimeEmailKind, OneTimeEmailService
from fixbackend.notification.notification_service import NotificationService
from fixcloudutils.util import utc

log = logging.getLogger(__name__)


class EmailOnSignupConsumer(Service):
    def __init__(
        self,
        notification_service: NotificationService,
        subscriber: DomainEventSubscriber,
    ) -> None:
        self.notification_service = notification_service
        subscriber.subscribe(UserRegistered, self.process_user_registered_event, "email_on_signup")

    async def process_user_registered_event(self, event: UserRegistered) -> None:
        message = Signup(recipient=event.email)
        await self.notification_service.send_message(to=event.email, message=message)


class ScheduleTrialEndReminder(Service):
    def __init__(
        self,
        subscriber: DomainEventSubscriber,
        one_time_email_service: OneTimeEmailService,
        listen_to_events: bool = True,
    ) -> None:
        self.one_time_email_service = one_time_email_service
        if listen_to_events:
            subscriber.subscribe(WorkspaceCreated, self._workspace_created_handler, "schedule_trial_end_reminder")

    async def _workspace_created_handler(self, event: WorkspaceCreated) -> None:
        await self.schedule_trial_end_reminder(
            event.workspace_id, schedule_at=utc() + trial_period_duration(), kind=OneTimeEmailKind.TrialEndNotification
        )

    async def schedule_trial_end_reminder(
        self, workspace_id: WorkspaceId, schedule_at: datetime, kind: OneTimeEmailKind
    ) -> None:
        for days_before_expiration in [2, 1]:
            await self.one_time_email_service.schedule_one_time_email(
                kind=kind,
                scheduled_at=schedule_at - timedelta(days=days_before_expiration),
                user_id=None,
                workspace_id=workspace_id,
                message=TrialExpiresSoon(days_till_expire=days_before_expiration),
            )

        await self.one_time_email_service.schedule_one_time_email(
            kind=kind,
            scheduled_at=schedule_at,
            user_id=None,
            workspace_id=workspace_id,
            message=TrialExpired(),
        )


class UnscheduleTrialEndReminder(Service):
    def __init__(
        self,
        subscriber: DomainEventSubscriber,
        one_time_email_service: OneTimeEmailService,
        listen_to_events: bool = True,
    ) -> None:
        self.one_time_email_service = one_time_email_service
        if listen_to_events:
            subscriber.subscribe(
                ProductTierChanged, self._product_tier_changed_handler, "unschedule_trial_end_reminder"
            )

    async def _product_tier_changed_handler(self, event: ProductTierChanged) -> None:
        moved_from_trial = event.previous_tier == ProductTier.Trial and event.product_tier != ProductTier.Trial
        if moved_from_trial:
            await self.unschedule_trial_end_reminder(event.workspace_id, kind=OneTimeEmailKind.TrialEndNotification)

    async def unschedule_trial_end_reminder(self, workspace_id: WorkspaceId, kind: OneTimeEmailKind) -> None:
        await self.one_time_email_service.unschedule_one_time_email(user_id=None, workspace_id=workspace_id, kind=kind)
