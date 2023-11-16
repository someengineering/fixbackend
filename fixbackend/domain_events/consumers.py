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
from httpx import AsyncClient, BasicAuth, Request

from fixbackend.config import Config
from fixbackend.domain_events.events import UserRegistered
from fixbackend.domain_events.subscriber import DomainEventSubscriber

log = logging.getLogger(__name__)


class CustomerIoEventConsumer(Service):
    def __init__(
        self,
        http_client: AsyncClient,
        config: Config,
        subscriber: DomainEventSubscriber,
    ) -> None:
        self.http_client = http_client
        self.site_id = config.customerio_site_id
        self.api_key = config.customerio_api_key
        self.customerio_baseurl = config.customerio_baseurl
        subscriber.subscribe(UserRegistered, self.process_user_registered_event, "customerio")

    async def process_user_registered_event(self, event: UserRegistered) -> None:
        if self.site_id is None or self.api_key is None:
            log.warning(f"No custemer.io credential configured, skipping registration. Event: {event}")
            return
        endpoint = f"{self.customerio_baseurl}/api/v2/entity"
        payload = {
            "type": "person",
            "identifiers": {"email": event.email},
            "action": "identify",
            "attributes": {},
        }
        auth = BasicAuth(username=self.site_id, password=self.api_key)
        request = Request(method="POST", url=endpoint, json=payload)
        resp = await self.http_client.send(request, auth=auth)
        if not resp.is_success:
            raise RuntimeError("Error registering user in customerio: " + resp.text)
