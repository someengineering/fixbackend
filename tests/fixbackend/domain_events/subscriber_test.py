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
from datetime import timedelta
from typing import Optional
from uuid import uuid4

import pytest
from fixcloudutils.redis.event_stream import RedisStreamPublisher
from redis.asyncio import Redis

from fixbackend.config import Config
from fixbackend.domain_events import DomainEventsStreamName
from fixbackend.domain_events.events import UserRegistered
from fixbackend.domain_events.publisher_impl import DomainEventPublisherImpl
from fixbackend.domain_events.subscriber import DomainEventSubscriber
from fixbackend.ids import UserId, WorkspaceId


@pytest.mark.asyncio
async def test_subscribe(redis: Redis, default_config: Config) -> None:
    subscriber = DomainEventSubscriber(redis, default_config)
    publisher = DomainEventPublisherImpl(
        RedisStreamPublisher(
            redis,
            DomainEventsStreamName,
            "dispatching",
            keep_unprocessed_messages_for=timedelta(days=7),
        ),
    )

    event = UserRegistered(user_id=UserId(uuid4()), email="foo", tenant_id=WorkspaceId(uuid4()))

    received_event: Optional[UserRegistered] = None
    received_event2: Optional[UserRegistered] = None

    async def handler(event: UserRegistered) -> None:
        nonlocal received_event
        received_event = event

    async def handler2(event: UserRegistered) -> None:
        nonlocal received_event2
        received_event2 = event

    subscriber.subscribe(UserRegistered, handler)
    subscriber.subscribe(UserRegistered, handler2)
    await subscriber.start()

    await publisher.publish(event)

    wait_count = 0

    while received_event2 is None or wait_count < 10:
        await asyncio.sleep(0.1)
        wait_count += 1

    assert received_event == event
    assert received_event2 == event

    await subscriber.stop()
