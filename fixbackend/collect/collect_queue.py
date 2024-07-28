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
from datetime import timedelta
from typing import Dict, Optional, ClassVar, List
from uuid import UUID

from arq import ArqRedis
from attrs import define
from cattrs.preconf.json import make_converter
from fixcloudutils.types import Json

from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.ids import CloudAccountId, AwsARN, ExternalId, CloudName, TaskId

log = logging.getLogger(__name__)

json_converter = make_converter()

json_converter.register_structure_hook(UUID, lambda v, _: UUID(v))
json_converter.register_unstructure_hook(UUID, lambda v: str(v))


class JobAlreadyEnqueued(Exception):
    """
    Job with the same name is already enqueued.
    """


class AccountInformation(ABC):
    kind: ClassVar[str] = "account_information"

    def to_json(self) -> Json:
        js: Json = json_converter.unstructure(self)
        js["kind"] = self.kind
        return js


@define
class AwsAccountInformation(AccountInformation):
    kind: ClassVar[str] = "aws_account_information"
    aws_account_id: CloudAccountId
    aws_account_name: Optional[str]
    aws_role_arn: AwsARN
    external_id: ExternalId


@define
class GcpProjectInformation(AccountInformation):
    kind: ClassVar[str] = "gcp_project_information"
    gcp_project_id: CloudAccountId
    google_application_credentials: Json  # GCP uses service account JSON to authenticate


@define
class AzureSubscriptionInformation(AccountInformation):
    kind: ClassVar[str] = "azure_subscription_information"
    azure_subscription_id: CloudAccountId
    tenant_id: str  # ID of the service principal's tenant. Also called its "directory" ID.
    client_id: str  # The service principal's client ID
    client_secret: str  # One of the service principal's client secrets


@define
class PostCollectAccountInfo:
    cloud: CloudName
    account_id: CloudAccountId
    task_id: TaskId

    def to_json(self) -> Json:
        return json_converter.unstructure(self)


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
        defer_by: Optional[timedelta] = None,
        retry_failed_for: Optional[timedelta] = None,
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
        :param defer_by: defer the job start by this amount of time.
        :param retry_failed_for: Retry failed jobs for this amount of time.
        :return: None
        """

    @abstractmethod
    async def enqueue_post_collect(
        self,
        db: GraphDatabaseAccess,
        accounts_collected: List[PostCollectAccountInfo],
        *,
        env: Optional[Dict[str, str]] = None,
        job_id: Optional[str] = None,
        wait_until_done: bool = False,
        defer_by: Optional[timedelta] = None,
        retry_failed_for: Optional[timedelta] = None,
    ) -> None:
        """
        Enqueue a post-collect job. This method will only put the job into the queue.

        :param db: The database access configuration.
        :param account: The account information to collect.
        :param env: The environment variables to pass to the worker.
        :param job_id: Globally unique identifier of this job.
               If provided and another job exists with the same id, the job will not be enqueued.
        :param wait_until_done: If true, this method will wait until the job is completed.
               This number is used to determine the assigned resources for this job (cpu / memory).
        :param defer_by: defer the job start by this amount of time.
        :param retry_failed_for: Retry failed jobs for this amount of time.
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
        defer_by: Optional[timedelta] = None,
        retry_failed_for: Optional[timedelta] = None,
    ) -> None:
        collect_job = dict(
            tenant_id=str(db.workspace_id),
            graphdb_server=db.server,
            graphdb_database=db.database,
            graphdb_username=db.username,
            graphdb_password=db.password,
            account=account.to_json(),
            env=env or {},
            retry_failed_for_seconds=retry_failed_for.total_seconds() if retry_failed_for else None,
        )
        job = await self.arq.enqueue_job("collect", collect_job, _job_id=job_id, _defer_by=defer_by)
        if job is None:
            raise JobAlreadyEnqueued(f"Failed to enqueue collect job {job_id}")
        log.info(f"Enqueuing collect job {job.job_id} for tenant={db.workspace_id}")
        if wait_until_done:
            # this will either return none or throw an exception (reraised from the worker)
            log.debug("Waiting for collect job to finish.")
            await job.result()

    async def enqueue_post_collect(
        self,
        db: GraphDatabaseAccess,
        accounts_collected: List[PostCollectAccountInfo],
        *,
        env: Optional[Dict[str, str]] = None,
        job_id: Optional[str] = None,
        wait_until_done: bool = False,
        defer_by: Optional[timedelta] = None,
        retry_failed_for: Optional[timedelta] = None,
    ) -> None:
        collect_job = dict(
            tenant_id=str(db.workspace_id),
            graphdb_server=db.server,
            graphdb_database=db.database,
            graphdb_username=db.username,
            graphdb_password=db.password,
            accounts_collected=[info.to_json() for info in accounts_collected],
            env=env or {},
            retry_failed_for_seconds=retry_failed_for.total_seconds() if retry_failed_for else None,
        )
        job = await self.arq.enqueue_job("post-collect", collect_job, _job_id=job_id, _defer_by=defer_by)
        if job is None:
            raise JobAlreadyEnqueued(f"Failed to enqueue collect job {job_id}")
        log.info(f"Enqueuing collect job {job.job_id} for tenant={db.workspace_id}")
        if wait_until_done:
            # this will either return none or throw an exception (reraised from the worker)
            log.debug("Waiting for collect job to finish.")
            await job.result()
