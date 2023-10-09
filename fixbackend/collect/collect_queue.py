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
import logging
from abc import ABC, abstractmethod
from typing import Dict, Optional, ClassVar

from arq import ArqRedis
from attrs import define
from cattr import unstructure
from fixcloudutils.types import Json

from fixbackend.graph_db.models import GraphDatabaseAccess

log = logging.getLogger(__name__)


class JobAlreadyEnqueued(Exception):
    """
    Job with the same name is already enqueued.
    """


class AccountInformation(ABC):
    kind: ClassVar[str] = "account_information"

    def to_json(self) -> Json:
        js: Json = unstructure(self)
        js["kind"] = self.kind
        return js


@define
class AwsAccountInformation(AccountInformation):
    kind: ClassVar[str] = "aws_account_information"
    aws_account_id: str
    aws_account_name: Optional[str]
    aws_role_arn: str
    external_id: str


class CollectQueue(ABC):
    @abstractmethod
    async def enqueue(
        self,
        db: GraphDatabaseAccess,
        account: AccountInformation,
        *,
        env: Optional[Dict[str, str]] = None,
        job_id: Optional[str] = None,
        wait_until_done: bool = False,
    ) -> None:
        """
        Enqueue a collect job. This method will only put the job into the queue.

        :param db: The database access configuration.
        :param account: The account information to collect.
        :param env: The environment variables to pass to the worker.
        :param job_id: Globally unique identifier of this job.
               If provided and another job exists with the same id, the job will not be enqueued.
        :param wait_until_done: If true, this method will wait until the job is completed.
               This number is used to determine the assigned resources for this job (cpu / memory).
        :return: None
        """


class RedisCollectQueue(CollectQueue):
    def __init__(self, arq: ArqRedis) -> None:
        self.arq = arq

    async def enqueue(
        self,
        db: GraphDatabaseAccess,
        account: AccountInformation,
        *,
        env: Optional[Dict[str, str]] = None,
        job_id: Optional[str] = None,
        wait_until_done: bool = False,
    ) -> None:
        collect_job = dict(
            tenant_id=str(db.workspace_id),
            graphdb_server=db.server,
            graphdb_database=db.database,
            graphdb_username=db.username,
            graphdb_password=db.password,
            account=account.to_json(),
            env=env or {},
        )
        job = await self.arq.enqueue_job("collect", collect_job, _job_id=job_id)
        if job is None:
            raise JobAlreadyEnqueued(f"Failed to enqueue collect job {job_id}")
        log.info(f"Enqueuing collect job {job.job_id} for tenant={db.workspace_id}")
        if wait_until_done:
            # this will either return none or throw an exception (reraised from the worker)
            log.debug("Waiting for collect job to finish.")
            await job.result()
