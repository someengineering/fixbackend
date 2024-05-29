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

import asyncio
from datetime import timedelta
from typing import Any, Dict, List
from google.oauth2 import service_account
from googleapiclient.discovery import build
from fixcloudutils.service import Service
import json
from fixbackend.cloud_accounts.models import GcpServiceAccountKey
from fixbackend.cloud_accounts.service import CloudAccountService
from fixbackend.ids import GcpServiceAccountKeyId, WorkspaceId
from fixbackend.cloud_accounts.gcp_service_account_repo import GcpServiceAccountKeyRepository

from fixcloudutils.asyncio.periodic import Periodic
from fixcloudutils.util import utc
from logging import getLogger

log = getLogger(__name__)


class GcpServiceAccountService(Service):

    def __init__(
        self,
        service_account_key_repo: GcpServiceAccountKeyRepository,
        cloud_account_service: CloudAccountService,
        dispatching: bool = False,
    ) -> None:
        self.dispatching = dispatching
        self.service_account_key_repo = service_account_key_repo
        self.cloud_account_service = cloud_account_service
        self.new_account_pinger = Periodic(
            "new_service_account_pinger", self._ping_new_service_account_keys, timedelta(minutes=1)
        )
        self.regular_account_healthcheck = Periodic(
            "service_account_healthcheck", self._service_account_healthcheck, timedelta(hours=1)
        )

    async def start(self) -> Any:
        if self.dispatching:
            await self.new_account_pinger.start()
            await self.regular_account_healthcheck.start()

    async def stop(self) -> None:
        if self.dispatching:
            await self.new_account_pinger.stop()
            await self.regular_account_healthcheck.stop()

    async def list_projects(self, service_account_key: str) -> List[Dict[str, Any]]:

        def blocking_call() -> List[Dict[str, Any]]:
            service_account_json = json.loads(service_account_key)
            SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

            credentials = service_account.Credentials.from_service_account_info(service_account_json, scopes=SCOPES)

            service = build("cloudresourcemanager", "v1", credentials=credentials)

            request = service.projects().list()

            projects = []

            while request is not None:
                response = request.execute()

                for project in response.get("projects", []):
                    projects.append(project)

                request = service.projects().list_next(previous_request=request, previous_response=response)

            return projects

        return await asyncio.to_thread(blocking_call)

    async def update_cloud_accounts(
        self, projects: List[Dict[str, Any]], tenant_id: WorkspaceId, key_id: GcpServiceAccountKeyId
    ) -> None:
        for project in projects:
            await self.cloud_account_service.create_gcp_account(
                workspace_id=tenant_id, account_id=project["projectId"], account_name=project.get("name"), key_id=key_id
            )

    async def _import_projects_from_service_account(self, key: GcpServiceAccountKey) -> None:
        try:
            projects = await self.list_projects(key.value)
        except Exception as e:
            log.info(f"Failed to list projects for service account key {key.id}, marking it as invalid: {e}")
            await self.service_account_key_repo.update_status(key.id, can_access_sa=False)
            return None
        await self.service_account_key_repo.update_status(key.id, can_access_sa=True)
        await self.update_cloud_accounts(projects, key.tenant_id, key.id)

    async def _ping_new_service_account_keys(self) -> None:
        created_less_than_30_minutes_ago = await self.service_account_key_repo.list_created_after(
            utc() - timedelta(minutes=30), only_valid_keys=False
        )

        async with asyncio.TaskGroup() as tg:
            for key in created_less_than_30_minutes_ago:
                tg.create_task(self._import_projects_from_service_account(key))

    async def _service_account_healthcheck(self) -> None:
        older_than_1_hour = await self.service_account_key_repo.list_created_before(
            utc() - timedelta(hours=1), only_valid_keys=True
        )

        async with asyncio.TaskGroup() as tg:
            for key in older_than_1_hour:
                tg.create_task(self._import_projects_from_service_account(key))
