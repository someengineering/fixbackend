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


from cattrs import unstructure
from fixcloudutils.redis.event_stream import RedisStreamPublisher

from fixbackend.domain_events.events import Event
from fixbackend.domain_events.sender import DomainEventSender


class DomainEventSenderImpl(DomainEventSender):
    def __init__(self, publisher: RedisStreamPublisher) -> None:
        self.publisher = publisher

    async def publish(self, event: Event) -> None:
        message = unstructure(event)
        await self.publisher.publish(kind=event.kind, message=message)
