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


from datetime import datetime, timedelta
from logging import getLogger
from typing import Any, Awaitable, Callable, Dict, Generic, Tuple, Type, TypeVar

from attrs import frozen
from fixcloudutils.redis.event_stream import MessageContext, RedisStreamListener
from fixcloudutils.service import Service
from fixcloudutils.types import Json
from redis.asyncio import Redis

from fixbackend.config import Config
from fixbackend.domain_events import DomainEventsStreamName
from fixbackend.domain_events.events import Event
import asyncio

Kind = str

Evt = TypeVar("Evt", bound=Event)


log = getLogger(__name__)


@frozen
class Callback(Generic[Evt]):
    callback: Callable[[Evt], Awaitable[None]]
    name: str


@frozen
class HandlerDescriptor(Generic[Evt]):
    callbacks: Tuple[Callback[Evt], ...]
    event_cls: Type[Evt]

    def with_callback(self, callback: Callable[[Evt], Awaitable[None]], name: str) -> "HandlerDescriptor[Evt]":
        return HandlerDescriptor(callbacks=self.callbacks + (Callback(callback, name),), event_cls=self.event_cls)


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
        )

    async def start(self) -> None:
        log.info("Starting domain event subscriber")
        await self.listener.start()

    async def stop(self) -> None:
        log.info("Stopping domain event subscriber")
        await self.listener.stop()

    def subscribe(self, event_cls: Type[Evt], handler: Callable[[Evt], Awaitable[None]], name: str) -> None:
        default_descriptor = HandlerDescriptor(event_cls=event_cls, callbacks=())
        existing = self.subscribers.get(event_cls.kind, default_descriptor)
        new_descriptor = existing.with_callback(handler, name)
        self.subscribers[event_cls.kind] = new_descriptor
        log.info(f"Added domain event handler {name} for {event_cls.kind}")

    async def timed(self, callback: Callback[Evt], event: Evt) -> None:
        log.info(f"Processing domain event: {event} with {callback.name}")
        before = datetime.utcnow()
        await callback.callback(event)
        after = datetime.utcnow()
        elapsed = after - before
        log.info(f"{callback.name} processed domain event {event} in {elapsed}")

    async def process_domain_event(self, message: Json, context: MessageContext) -> None:
        log.info(f"Processing domain event: {message} {context}")
        handler = self.subscribers.get(context.kind)
        log.info(f"subscribers: {self.subscribers} Handler: {handler}")
        if not handler:
            return
        event = handler.event_cls.from_json(message)
        async with asyncio.TaskGroup() as g:
            for callback in handler.callbacks:
                g.create_task(self.timed(callback, event))
        log.info(f"Processed domain event {event}")
