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
from asyncio import Lock
from datetime import timedelta
from typing import List, Optional, Any

from fixcloudutils.asyncio.periodic import Periodic
from fixcloudutils.types import Json
from httpx import AsyncClient

from fixbackend.analytics import AnalyticsEventSender
from fixbackend.analytics.events import AnalyticsEvent
from fixbackend.utils import group_by, md5

log = logging.getLogger(__name__)


class NoAnalyticsEventSender(AnalyticsEventSender):
    async def send(self, event: AnalyticsEvent) -> None:
        log.info(f"Would send analytics event: {event.kind}")


class GoogleAnalyticsEventSender(AnalyticsEventSender):
    def __init__(
        self,
        client: AsyncClient,
        measurement_id: str,
        api_secret: str,
    ) -> None:
        super().__init__()
        self.client = client
        self.measurement_id = measurement_id
        self.api_secret = api_secret
        self.events: List[AnalyticsEvent] = []
        self.lock = Lock()
        self.sender = Periodic("send_events", self.send_events, timedelta(seconds=30))
        self.event_handler: Optional[Any] = None

    async def start(self) -> None:
        await self.sender.start()

    async def stop(self) -> None:
        await self.sender.stop()
        # send all remaining events
        await self.send_events()

    async def send(self, event: AnalyticsEvent) -> None:
        async with self.lock:
            self.events.append(event)

    async def send_events(self) -> None:
        def event_to_json(event: AnalyticsEvent) -> Json:
            ev = event.to_json()
            ev.pop("user_id", None)
            return dict(name=event.kind, params=ev)

        # return early, if there are no events to send
        if not self.events:
            return

        # swap out the events list, so that we can send the events in the background
        async with self.lock:
            events = self.events
            self.events = []

        # group events by user_id
        counter = 0
        for user_id, user_events in group_by(events, lambda e: e.user_id).items():
            client_id = md5(user_id)  # The md5 hash of the internal user id. Also used in the frontend.
            # GA4 expects a maximum of 25 events per request
            for i in range(0, len(user_events), 25):
                batch = events[i : i + 25]  # noqa: E203
                try:
                    counter += 1
                    response = await self.client.post(
                        "https://www.google-analytics.com/mp/collect",
                        params=dict(measurement_id=self.measurement_id, api_secret=self.api_secret),
                        headers={"User-Agent": "fixbackend"},
                        json=dict(client_id=client_id, events=[event_to_json(e) for e in batch]),
                    )
                    if response.status_code != 204:
                        log.warning(f"Error sending events to Google Analytics: {response.status_code}:{response.text}")
                except Exception as ex:
                    log.warning(f"Error sending events to Google Analytics: {ex}")

        if counter:
            log.info(f"Sent {counter} events to Google Analytics")
