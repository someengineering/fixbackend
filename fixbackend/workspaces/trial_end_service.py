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
from datetime import timedelta
from typing import Any, Optional

from fixcloudutils.asyncio.periodic import Periodic
from fixcloudutils.service import Service

from fixbackend.cloud_accounts.service import CloudAccountService
from fixbackend.config import ProductTierSettings
from fixbackend.domain_events.events import ProductTierChanged
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.ids import ProductTier
from fixbackend.types import AsyncSessionMaker
from fixbackend.workspaces.repository import WorkspaceRepository

log = logging.getLogger(__name__)


class TrialEndService(Service):

    def __init__(
        self,
        workspace_repository: WorkspaceRepository,
        session_maker: AsyncSessionMaker,
        cloud_account_service: CloudAccountService,
        domain_event_publisher: DomainEventPublisher,
    ):
        self.workspace_repository = workspace_repository
        self.cloud_account_service = cloud_account_service
        self.session_maker = session_maker
        self.move_trials_to_free: Optional[Periodic] = Periodic(
            "move_trials_to_free_tier", self.move_trials_to_free_tier, timedelta(minutes=60)
        )
        self.trial_period_duration = timedelta(days=14)
        self.idle_period_duration = timedelta(days=30)
        self.domain_event_publisher = domain_event_publisher

    async def start(self) -> Any:
        if self.move_trials_to_free:
            await self.move_trials_to_free.start()

    async def stop(self) -> None:
        if self.move_trials_to_free:
            await self.move_trials_to_free.stop()

    async def move_trials_to_free_tier(self) -> None:
        async with self.session_maker() as session:
            workspaces = await self.workspace_repository.list_expired_trials(
                been_in_trial_tier_for=self.trial_period_duration, session=session
            )
            for workspace in workspaces:
                new_tier = ProductTier.Free
                if limit := ProductTierSettings[new_tier].account_limit:
                    await self.cloud_account_service.disable_cloud_accounts(workspace.id, limit)
                log.info(f"Moving workspace {workspace.id} to free tier from trial tier because trial has expired.")
                await self.workspace_repository.update_product_tier(workspace.id, new_tier, session=session)

    async def cleanup_old_trials_and_not_paying(self) -> None:
        async with self.session_maker() as session:
            workspaces = await self.workspace_repository.list_expired_trials(
                been_in_trial_tier_for=self.trial_period_duration + self.idle_period_duration, session=session
            )
            for workspace in workspaces:
                log.info(f"Cleaning up workspace {workspace.id} because trial has expired.")
                await self.workspace_repository.remove_all_users_but_owner(workspace.id, session=session)
                event = ProductTierChanged(
                    workspace_id=workspace.id,
                    user_id=workspace.owner_id,
                    product_tier=ProductTier.Free,
                    is_paid_tier=False,
                    is_higher_tier=False,
                    previous_tier=workspace.product_tier,
                )
                await self.domain_event_publisher.publish(event)
