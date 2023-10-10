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


from typing import Optional, Tuple
import uuid
import pytest
from fixbackend.domain_events.sender_impl import DomainEventSenderImpl
from fixbackend.domain_events.events import AwsAccountDiscovered
from fixcloudutils.redis.event_stream import RedisStreamPublisher
from fixcloudutils.types import Json
from cattrs import unstructure
from fixbackend.ids import CloudAccountId, WorkspaceId


class RedisStreamPublisherMock(RedisStreamPublisher):
    def __init__(self) -> None:
        self.last_message: Optional[Tuple[str, Json]] = None

    async def publish(self, kind: str, message: Json) -> None:
        self.last_message = (kind, message)


@pytest.mark.asyncio
async def test_publish_event() -> None:
    stream_publisher = RedisStreamPublisherMock()
    sender = DomainEventSenderImpl(stream_publisher)
    event = AwsAccountDiscovered(
        cloud_account_id=CloudAccountId(uuid.uuid4()),
        tenant_id=WorkspaceId(uuid.uuid4()),
        cloud_id="aws",
        aws_account_id="123456789012",
    )
    await sender.publish(event)

    assert stream_publisher.last_message is not None
    assert stream_publisher.last_message[0] == event.kind
    assert stream_publisher.last_message[1] == unstructure(event)
