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
from typing import Optional, Dict, Awaitable, Callable
from uuid import uuid4

import pytest
from fixcloudutils.redis.event_stream import RedisStreamPublisher, Backoff
from redis.asyncio import Redis

from fixbackend.config import Config
from fixbackend.domain_events import DomainEventsStreamName
from fixbackend.domain_events.events import UserRegistered, AwsAccountConfigured
from fixbackend.domain_events.publisher_impl import DomainEventPublisherImpl
from fixbackend.domain_events.subscriber import DomainEventSubscriber, HandlerDescriptor
from fixbackend.ids import UserId, WorkspaceId, CloudAccountId, FixCloudAccountId


@pytest.mark.asyncio
async def test_subscribe(redis: Redis, default_config: Config) -> None:
    subscriber = DomainEventSubscriber(redis, default_config, "test-subscriber")
    publisher = DomainEventPublisherImpl(
        RedisStreamPublisher(
            redis,
            DomainEventsStreamName,
            "dispatching",
            keep_unprocessed_messages_for=timedelta(days=7),
        ),
    )

    event = UserRegistered(user_id=UserId(uuid4()), email="foo", tenant_id=WorkspaceId(uuid4()))
    aws_event = AwsAccountConfigured(
        cloud_account_id=FixCloudAccountId(uuid4()),
        tenant_id=WorkspaceId(uuid4()),
        aws_account_id=CloudAccountId("123456"),
    )

    received_event: Optional[UserRegistered] = None
    received_event2: Optional[UserRegistered] = None
    handler2_failed = False
    account_configured_event: Optional[AwsAccountConfigured] = None

    async def handler(event: UserRegistered) -> None:
        nonlocal received_event
        received_event = event

    async def handler2(event: UserRegistered) -> None:
        nonlocal received_event2
        nonlocal handler2_failed
        if not handler2_failed:
            handler2_failed = True
            raise Exception("foo")
        received_event2 = event

    async def handler3(event: AwsAccountConfigured) -> None:
        nonlocal account_configured_event
        account_configured_event = event

    subscriber.subscribe(UserRegistered, handler, "handler1")
    subscriber.subscribe(UserRegistered, handler2, "handler2")
    subscriber.subscribe(AwsAccountConfigured, handler3, "handler3")
    await subscriber.start()

    await publisher.publish(event)
    await publisher.publish(aws_event)

    wait_count = 0

    while account_configured_event is None or wait_count < 10:
        await asyncio.sleep(0.1)
        wait_count += 1

    assert received_event == event
    assert received_event2 == event
    assert account_configured_event == aws_event

    await subscriber.stop()


async def test_handler() -> None:
    counter: Dict[int, int] = defaultdict(int)

    def fail_times(num: int) -> Callable[[UserRegistered], Awaitable[None]]:
        count = num

        async def handle_event(event: UserRegistered) -> None:
            nonlocal count
            counter[num] += 1
            count -= 1
            if count > 0:
                raise Exception("foo")
            return None

        return handle_event

    fast_backoff = Backoff(0, 1, 5)
    handler = HandlerDescriptor.create(UserRegistered)
    handler = handler.with_callback(fail_times(1), "handler1", fast_backoff)
    handler = handler.with_callback(fail_times(2), "handler2", fast_backoff)
    handler = handler.with_callback(fail_times(3), "handler3", fast_backoff)
    handler = handler.with_callback(fail_times(4), "handler4", fast_backoff)
    await handler.call(UserRegistered(user_id=UserId(uuid4()), email="foo", tenant_id=WorkspaceId(uuid4())))
    assert len(counter) == 4
    for k, v in counter.items():
        assert k == v  # expect that the handler k is attempted k times
