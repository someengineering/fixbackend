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


import logging
from datetime import timedelta
from typing import Any, Optional

from fixcloudutils.asyncio.periodic import Periodic
from fixcloudutils.service import Service

from fixbackend.cloud_accounts.service import CloudAccountService
from fixbackend.config import ProductTierSettings, trial_period_duration
from fixbackend.ids import ProductTier
from fixbackend.types import AsyncSessionMaker
from fixbackend.workspaces.repository import WorkspaceRepository

log = logging.getLogger(__name__)


free_tier_cleanup_timeout = timedelta(days=14)


class FreeTierCleanupService(Service):

    def __init__(
        self,
        workspace_repository: WorkspaceRepository,
        session_maker: AsyncSessionMaker,
        cloud_account_service: CloudAccountService,
    ):
        self.workspace_repository = workspace_repository
        self.cloud_account_service = cloud_account_service
        self.session_maker = session_maker
        self.periodic: Optional[Periodic] = Periodic(
            "clean_up_free_tiers",
            self.cleanup_free_tiers,
            frequency=timedelta(minutes=60),
            first_run=timedelta(seconds=30),
        )

    async def start(self) -> Any:
        if self.periodic:
            await self.periodic.start()

    async def stop(self) -> None:
        if self.periodic:
            await self.periodic.stop()

    async def cleanup_free_tiers(self) -> None:
        workspaces = await self.workspace_repository.list_overdue_free_tier_cleanup(
            been_in_free_tier_for=trial_period_duration() + free_tier_cleanup_timeout
        )
        for workspace in workspaces:

            if limit := ProductTierSettings[ProductTier.Free].account_limit:
                log.info(
                    f"Cleaning up workspace {workspace.id}"
                    " because it has been in free tier for"
                    f"{free_tier_cleanup_timeout}."
                )
                accounts = await self.cloud_account_service.list_accounts(workspace.id)
                for i, account in enumerate(accounts):
                    if i < limit:
                        continue

                    log.info(
                        f"Deleting cloud account {account.id} on workspace {workspace.id} "
                        "because it is over the limit."
                    )
                    await self.cloud_account_service.delete_cloud_account(workspace.owner_id, account.id, workspace.id)
