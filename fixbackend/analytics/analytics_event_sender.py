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
from __future__ import annotations

import asyncio
import logging
import uuid
from asyncio import Lock
from collections import deque
from datetime import timedelta
from typing import List, Optional, Any
from typing import MutableSequence

from async_lru import alru_cache
from fixcloudutils.asyncio.periodic import Periodic
from fixcloudutils.service import Service
from fixcloudutils.types import Json
from fixcloudutils.util import uuid_str
from httpx import AsyncClient
from posthog.client import Client
from prometheus_client import Counter

from fixbackend.analytics import AnalyticsEventSender
from fixbackend.analytics.events import AEWorkspaceCreated, AEUserRegistered
from fixbackend.analytics.events import AnalyticsEvent
from fixbackend.ids import WorkspaceId, UserId
from fixbackend.utils import group_by, md5
from fixbackend.workspaces.repository import WorkspaceRepository

log = logging.getLogger(__name__)

AnalyticsCounter = Counter("fixbackend_analytics_events", "Fixbackend Analytics Events", ["kind"])


class NoAnalyticsEventSender(AnalyticsEventSender):
    async def send(self, event: AnalyticsEvent) -> None:
        log.info(f"Would send analytics event: {event.kind}")

    async def user_id_from_workspace(self, workspace_id: WorkspaceId) -> UserId:
        return UserId(uuid.uuid5(uuid.NAMESPACE_DNS, "fixbackend"))


class MultiAnalyticsEventSender(AnalyticsEventSender, Service):
    def __init__(self, senders: List[AnalyticsEventSender]) -> None:
        self.senders = senders
        self.event_handler: Optional[Any] = None

    async def send(self, event: AnalyticsEvent) -> None:
        for sender in self.senders:
            await sender.send(event)

    async def user_id_from_workspace(self, workspace_id: WorkspaceId) -> UserId:
        for sender in self.senders:
            return await sender.user_id_from_workspace(workspace_id)
        raise ValueError("No senders configured")

    async def start(self) -> Any:
        for sender in self.senders:
            await sender.start()

    async def stop(self) -> None:
        for sender in self.senders:
            await sender.stop()


class GoogleAnalyticsEventSender(AnalyticsEventSender):
    def __init__(
        self, client: AsyncClient, measurement_id: str, api_secret: str, workspace_repo: WorkspaceRepository
    ) -> None:
        super().__init__()
        self.client = client
        self.measurement_id = measurement_id
        self.api_secret = api_secret
        self.workspace_repo = workspace_repo
        self.events: List[AnalyticsEvent] = []
        self.lock = Lock()
        self.sender = Periodic("send_events", self.send_events, timedelta(seconds=30))

    async def start(self) -> None:
        await self.sender.start()

    async def stop(self) -> None:
        await self.sender.stop()
        # send all remaining events
        await self.send_events()

    async def send(self, event: AnalyticsEvent) -> None:
        async with self.lock:
            AnalyticsCounter.labels(kind=event.kind).inc()
            self.events.append(event)

    async def send_events(self) -> None:
        def event_to_json(event: AnalyticsEvent) -> Json:
            ev = event.to_json()
            ev.pop("user_id", None)
            return dict(name=event.kind, params=ev)

        # return early if there are no events to send
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

    @alru_cache(maxsize=1024)
    async def user_id_from_workspace(self, workspace_id: WorkspaceId) -> UserId:
        if workspace := await self.workspace_repo.get_workspace(workspace_id):
            return workspace.owner_id
        else:
            return UserId(uuid.uuid5(uuid.NAMESPACE_DNS, "fixbackend"))


class PostHogEventSender(AnalyticsEventSender):
    def __init__(
        self,
        api_key: str,
        workspace_repo: WorkspaceRepository,
        flush_at: int = 100,
        interval: timedelta = timedelta(minutes=1),
        host: str = "https://eu.posthog.com",
    ) -> None:
        super().__init__()
        self.client = Client(  # type: ignore
            project_api_key=api_key, host=host, flush_interval=0.5, max_retries=3, gzip=True
        )
        self.workspace_repo = workspace_repo
        self.run_id = uuid_str()  # create a unique id for this instance run
        self.queue: MutableSequence[AnalyticsEvent] = deque()
        self.flush_at = flush_at
        self.flusher = Periodic("flush_analytics", self.flush, interval)
        self.lock = asyncio.Lock()

    async def send(self, event: AnalyticsEvent) -> None:
        async with self.lock:
            self.queue.append(event)

        if len(self.queue) >= self.flush_at:
            await self.flush()

    @alru_cache(maxsize=1024)
    async def user_id_from_workspace(self, workspace_id: WorkspaceId) -> UserId:
        if workspace := await self.workspace_repo.get_workspace(workspace_id):
            return workspace.owner_id
        else:
            raise ValueError(f"Workspace with id {workspace_id} not found")

    async def flush(self) -> None:
        async with self.lock:
            for event in self.queue:
                # when a user is registered, identify it as user
                if isinstance(event, AEUserRegistered):
                    self.client.identify(  # type: ignore
                        distinct_id=str(event.user_id),
                        properties={"email": event.email},
                        timestamp=event.created_at,
                        uuid=event.id,
                    )
                # when a workspace is created, identify it as a group
                if isinstance(event, AEWorkspaceCreated):
                    self.client.group_identify(  # type: ignore
                        group_type="workspace_id",
                        group_key=str(event.workspace_id),
                        properties={"name": event.name, "slug": event.slug},
                        timestamp=event.created_at,
                        uuid=event.id,
                    )
                # if the event has a workspace_id, use it to define the group
                groups = {"workspace_id": str(ws)} if (ws := getattr(event, "workspace_id", None)) else None
                log.info(f"Send analytics event to posthog: {event.kind} user={event.user_id}, id={event.id}")
                self.client.capture(  # type: ignore
                    distinct_id=str(event.user_id),
                    event=event.kind,
                    properties=event.to_json(),
                    timestamp=event.created_at,
                    groups=groups,
                    uuid=event.id,
                )
            self.queue.clear()

    async def start(self) -> PostHogEventSender:
        await self.flusher.start()
        return self

    async def stop(self) -> None:
        await self.flusher.stop()
        await self.flush()
        self.client.shutdown()  # type: ignore
