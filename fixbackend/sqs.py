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
import asyncio
import json
import logging
from asyncio import Task
from datetime import timedelta
from functools import partial
from typing import Callable, Awaitable, Any, Optional

import boto3
from botocore.exceptions import ClientError
from fixcloudutils.asyncio import stop_running_task
from fixcloudutils.asyncio.async_extensions import run_async
from fixcloudutils.redis.event_stream import Backoff, NoBackoff, MessageContext
from fixcloudutils.service import Service
from fixcloudutils.types import Json
from fixcloudutils.util import utc, utc_str, parse_utc_str
from prometheus_client import Counter

log = logging.getLogger(__name__)

MessageProcessingFailed = Counter("sqs_processing_failed", "Messages failed to process", ["queue", "last_attempt"])
MessagesProcessed = Counter("sqs_messages_processed", "Messages processed", ["queue"])


class SQSRawListener(Service):
    """
    Listens to an AWS SQS queue and processes messages as they arrive.
    """

    def __init__(
        self,
        session: boto3.Session,
        queue_url: str,
        message_processor: Callable[[Json], Awaitable[Any]],
        *,
        consider_failed_after: Optional[timedelta] = None,
        max_nr_of_messages_in_one_batch: Optional[int] = None,
        wait_for_new_messages_to_arrive: Optional[timedelta] = None,
        do_not_retry_message_more_than: int = 5,
        backoff: Optional[Backoff] = Backoff(0.1, 10, 10),
    ) -> None:
        """
        :param queue_url: the url of the queue to listen to.
        :param message_processor: The function to call for each message.
        :param consider_failed_after: The time after which a message is considered failed.
                                      The message will become visible again in the queue and will be processed again.
        :param max_nr_of_messages_in_one_batch: The maximum number of messages to process in one batch.
        :param wait_for_new_messages_to_arrive: The time to wait for new messages to arrive.
        :param backoff: The backoff strategy to use when processing messages.
        """
        self.sqs = session.client("sqs")
        self.queue_url = queue_url
        self.message_processor = message_processor
        self.consider_failed_after = int(consider_failed_after.total_seconds()) if consider_failed_after else 30
        self.max_nr_of_messages_in_one_batch = max_nr_of_messages_in_one_batch or 10
        self.wait_for_new_messages_to_arrive = (
            int(wait_for_new_messages_to_arrive.total_seconds()) if wait_for_new_messages_to_arrive else 1
        )
        self.do_not_retry_message_more_than = do_not_retry_message_more_than
        self.backoff = backoff or NoBackoff
        self.__should_run = True
        self.__listen_task: Optional[Task[Any]] = None

    async def start(self) -> None:
        self.__should_run = True
        self.__listen_task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        self.__should_run = False
        await stop_running_task(self.__listen_task)

    async def _listen(self) -> None:
        while self.__should_run:
            try:
                log.debug("Polling SQS for messages")
                response = await run_async(
                    self.sqs.receive_message,
                    QueueUrl=self.queue_url,
                    AttributeNames=["All"],
                    MaxNumberOfMessages=self.max_nr_of_messages_in_one_batch,
                    VisibilityTimeout=self.consider_failed_after,
                    WaitTimeSeconds=self.wait_for_new_messages_to_arrive,
                )
                started = utc()
                for message in response.get("Messages", []):
                    if (utc() - started).total_seconds() >= self.consider_failed_after:
                        # do not process messages that are overdue
                        break
                    receipt_handle = message["ReceiptHandle"]
                    attributes = message.get("Attributes", {})
                    receive_count = int(attributes.get("ApproximateReceiveCount", "0"))
                    if receive_count <= self.do_not_retry_message_more_than:
                        try:
                            await self.backoff.with_backoff(partial(self.message_processor, message))
                            MessagesProcessed.labels(queue=self.queue_url).inc()
                        except Exception as ex:
                            log.exception(f"Error handling message: {ex}")
                            MessageProcessingFailed.labels(queue=self.queue_url, last_attempt="no").inc()
                            continue  # do not delete the message, but continue with the remaining messages
                    else:
                        log.warning(f"Message was received too often. Will not process: {message}")
                        MessageProcessingFailed.labels(queue=self.queue_url, last_attempt="yes").inc()
                    # Delete the message from the queue
                    await run_async(self.sqs.delete_message, QueueUrl=self.queue_url, ReceiptHandle=receipt_handle)
            except ClientError as ex:
                log.error(f"Error while polling SQS: {ex}")
                await asyncio.sleep(1)
            except Exception as ex:
                log.exception(f"Unexpected error: {ex}")


class SQSListener(SQSRawListener):
    """
    Process messages published by a SQSPublisher.
    """

    def __init__(
        self,
        session: boto3.Session,
        queue_url: str,
        message_processor: Callable[[Json, MessageContext], Awaitable[Any]],
        **kwargs: Any,
    ) -> None:
        super().__init__(session, queue_url, self.__context_handler(message_processor), **kwargs)

    @staticmethod
    def __context_handler(fn: Callable[[Json, MessageContext], Awaitable[Any]]) -> Callable[[Json], Awaitable[Any]]:
        async def handler(message: Json) -> Any:
            body = json.loads(message["Body"])
            context = MessageContext(
                id=message["MessageId"],
                kind=body["kind"],
                publisher=body["publisher"],
                sent_at=parse_utc_str(body["at"]),
                received_at=utc(),
            )
            return await fn(body["data"], context)

        return handler


class SQSPublisher(Service):
    def __init__(self, session: boto3.Session, publisher_name: str, queue_url: str) -> None:
        self.publisher_name = publisher_name
        self.sqs = session.client("sqs")
        self.queue_url = queue_url

    async def publish(self, kind: str, message: Json) -> None:
        to_send = {
            "at": utc_str(),
            "publisher": self.publisher_name,
            "kind": kind,
            "data": json.dumps(message),
        }
        await run_async(self.sqs.send_message, QueueUrl=self.queue_url, MessageBody=json.dumps(to_send))
