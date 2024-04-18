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


import logging

from fixcloudutils.service import Service

from fixbackend.domain_events.events import UserRegistered
from fixbackend.domain_events.subscriber import DomainEventSubscriber
from fixbackend.notification.email.email_messages import Signup
from fixbackend.notification.notification_service import NotificationService

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
