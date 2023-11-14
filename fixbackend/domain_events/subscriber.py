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


from datetime import timedelta
from typing import Awaitable, Callable, Dict, Type, Tuple, TypeVar, Generic, Any

from fixcloudutils.redis.event_stream import RedisStreamListener, MessageContext
from fixcloudutils.service import Service
from fixcloudutils.types import Json
from redis.asyncio import Redis

from fixbackend.config import Config
from fixbackend.domain_events import DomainEventsStreamName
from fixbackend.domain_events.events import Event
from attrs import frozen

Kind = str

Evt = TypeVar("Evt", bound=Event)


@frozen
class HandlerDescriptor(Generic[Evt]):
    callbacks: Tuple[Callable[[Evt], Awaitable[None]], ...]
    event_cls: Type[Evt]

    def with_callback(self, callback: Callable[[Evt], Awaitable[None]]) -> "HandlerDescriptor[Evt]":
        return HandlerDescriptor(callbacks=self.callbacks + (callback,), event_cls=self.event_cls)


class DomainEventSubscriber(Service):
    def __init__(self, redis: Redis, config: Config) -> None:
        self.redis = redis
        self.subscribers: Dict[Kind, HandlerDescriptor[Any]] = {}
        self.listener = RedisStreamListener(
            redis,
            DomainEventsStreamName,
            group="fixbackend-domain-events-subscriber",
            listener=config.instance_id,
            message_processor=self.process_domain_event,
            consider_failed_after=timedelta(minutes=5),
        )

    async def start(self) -> None:
        await self.listener.start()

    async def stop(self) -> None:
        await self.listener.stop()

    def subscribe(self, event_cls: Type[Evt], handler: Callable[[Evt], Awaitable[None]]) -> None:
        default_descriptor = HandlerDescriptor(event_cls=event_cls, callbacks=())
        existing = self.subscribers.get(event_cls.kind, default_descriptor)
        new_descriptor = existing.with_callback(handler)
        self.subscribers[event_cls.kind] = new_descriptor

    async def process_domain_event(self, message: Json, context: MessageContext) -> None:
        handler = self.subscribers.get(context.kind)
        if not handler:
            return
        event = handler.event_cls.from_json(message)
        for callback in handler.callbacks:
            await callback(event)
