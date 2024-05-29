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
import asyncio
from collections import defaultdict
from datetime import timedelta
from functools import partial
from logging import getLogger
from typing import Any, Awaitable, Callable, Dict, Generic, Tuple, Type, TypeVar, Optional

from attrs import frozen
from fixcloudutils.redis.event_stream import MessageContext, RedisStreamListener, Backoff, NoBackoff, DefaultBackoff
from fixcloudutils.service import Service
from fixcloudutils.types import Json
from fixcloudutils.util import utc

from fixbackend.config import Config
from fixbackend.domain_events import DomainEventsStreamName
from fixbackend.domain_events.events import Event
from fixbackend.types import Redis

Kind = str

Evt = TypeVar("Evt", bound=Event)


log = getLogger(__name__)


@frozen
class Callback(Generic[Evt]):
    callback: Callable[[Evt], Awaitable[None]]
    name: str
    backoff: Backoff

    async def call(self, event: Evt) -> None:
        before = utc()
        await self.backoff.with_backoff(partial(self.callback, event))
        elapsed = utc() - before
        log.debug(f"{self.name} processed domain event {event} in {elapsed}")


@frozen
class HandlerDescriptor(Generic[Evt]):
    callbacks: Tuple[Callback[Evt], ...]
    event_cls: Type[Evt]

    async def call(self, event: Evt) -> None:
        async with asyncio.TaskGroup() as g:
            for callback in self.callbacks:
                g.create_task(callback.call(event))

    def with_callback(
        self, callback: Callable[[Evt], Awaitable[None]], name: str, backoff: Backoff
    ) -> "HandlerDescriptor[Evt]":
        return HandlerDescriptor(
            callbacks=self.callbacks + (Callback(callback, name, backoff),), event_cls=self.event_cls
        )

    @staticmethod
    def create(event_cls: Type[Evt]) -> "HandlerDescriptor[Evt]":
        return HandlerDescriptor(callbacks=(), event_cls=event_cls)


T = TypeVar("T")


class DomainEventSubscriber(Service):
    def __init__(self, redis: Redis, config: Config, component: str) -> None:
        self.redis = redis
        self.subscribers: Dict[Kind, HandlerDescriptor[Any]] = {}
        self.listener = RedisStreamListener(
            redis,
            DomainEventsStreamName,
            group=f"fixbackend-domain-events-subscriber-{component}",
            listener=config.instance_id,
            message_processor=self.process_domain_event,
            consider_failed_after=timedelta(minutes=5),
            backoff=defaultdict(lambda: NoBackoff),  # no backoff for the whole message but for each handler
        )

    async def start(self) -> None:
        log.info("Starting domain event subscriber")
        await self.listener.start()

    async def stop(self) -> None:
        log.info("Stopping domain event subscriber")
        await self.listener.stop()

    def subscribe(
        self,
        event_cls: Type[Evt],
        handler: Callable[[Evt], Awaitable[None]],
        name: str,
        backoff: Optional[Backoff] = None,
    ) -> None:
        existing = self.subscribers.get(event_cls.kind, HandlerDescriptor.create(event_cls))
        self.subscribers[event_cls.kind] = existing.with_callback(handler, name, backoff or DefaultBackoff)
        log.info(f"Added domain event handler {name} for {event_cls.kind}")

    async def process_domain_event(self, message: Json, context: MessageContext) -> None:
        handler = self.subscribers.get(context.kind)
        if not handler:
            return
        event = handler.event_cls.from_json(message)
        log.info(f"Processing domain event {event}")
        await handler.call(event)
