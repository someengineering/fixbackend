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
import uuid
from functools import lru_cache

from httpx import AsyncClient

from fixbackend.analytics import AnalyticsEventSender
from fixbackend.analytics.analytics_event_sender import GoogleAnalyticsEventSender, NoAnalyticsEventSender
from fixbackend.analytics.events import (
    AEUserRegistered,
    AEAwsAccountDiscovered,
    AEAwsAccountConfigured,
    AEAwsAccountDeleted,
    AEAwsAccountDegraded,
    AEWorkspaceCreated,
    AEInvitationAccepted,
    AEUserJoinedWorkspace,
    AESecurityTierUpdated,
)
from fixbackend.config import Config
from fixbackend.domain_events.events import (
    UserRegistered,
    AwsAccountDiscovered,
    AwsAccountConfigured,
    AwsAccountDeleted,
    AwsAccountDegraded,
    CloudAccountNameChanged,
    WorkspaceCreated,
    InvitationAccepted,
    UserJoinedWorkspace,
    SecurityTierUpdated,
    Event,
)
from fixbackend.domain_events.subscriber import DomainEventSubscriber
from fixbackend.ids import UserId, WorkspaceId
from fixbackend.workspaces.repository import WorkspaceRepository

log = logging.getLogger(__name__)


class DomainEventToAnalyticsEventHandler:
    def __init__(
        self,
        instance_id: str,
        domain_event_subscriber: DomainEventSubscriber,
        sender: AnalyticsEventSender,
        workspace_repo: WorkspaceRepository,
    ) -> None:
        self.sender = sender
        self.workspace_repo = workspace_repo
        self.fixbackend_user_id = UserId(uuid.uuid5(uuid.NAMESPACE_DNS, instance_id))
        domain_event_subscriber.subscribe(UserRegistered, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(AwsAccountDiscovered, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(AwsAccountConfigured, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(AwsAccountDeleted, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(AwsAccountDegraded, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(CloudAccountNameChanged, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(WorkspaceCreated, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(InvitationAccepted, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(UserJoinedWorkspace, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(SecurityTierUpdated, self.handle, "domain_event_to_analytics")

    @lru_cache(maxsize=1024)
    async def user_id_from_workspace(self, workspace_id: WorkspaceId) -> UserId:
        if (workspace := await self.workspace_repo.get_workspace(workspace_id)) and (workspace.all_users()):
            return workspace.all_users()[0]
        else:
            return self.fixbackend_user_id

    async def handle(self, event: Event) -> None:
        match event:
            case UserRegistered() as event:
                await self.sender.send(AEUserRegistered(event.user_id, event.tenant_id))
            case AwsAccountDiscovered() as event:
                user_id = await self.user_id_from_workspace(event.tenant_id)
                await self.sender.send(AEAwsAccountDiscovered(user_id, event.tenant_id))
            case AwsAccountConfigured() as event:
                await self.sender.send(AEAwsAccountConfigured(self.fixbackend_user_id, event.tenant_id))
            case AwsAccountDeleted() as event:
                await self.sender.send(AEAwsAccountDeleted(event.user_id, event.tenant_id))
            case AEAwsAccountDegraded() as event:
                await self.sender.send(AEAwsAccountDegraded(self.fixbackend_user_id, event.workspace_id, event.error))
            case WorkspaceCreated() as event:
                await self.sender.send(AEWorkspaceCreated(event.user_id, event.workspace_id))
            case InvitationAccepted() as event:
                user_id = event.user_id or await self.user_id_from_workspace(event.workspace_id)
                await self.sender.send(AEInvitationAccepted(user_id, event.workspace_id))
            case UserJoinedWorkspace() as event:
                await self.sender.send(AEUserJoinedWorkspace(event.user_id, event.workspace_id))
            case SecurityTierUpdated() as event:
                await self.sender.send(AESecurityTierUpdated(event.user_id, event.workspace_id, event.security_tier))
            case _:
                log.error(f"Does not know how to handle event: {event}")


def analytics(
    config: Config,
    client: AsyncClient,
    domain_event_subscriber: DomainEventSubscriber,
    workspace_repo: WorkspaceRepository,
) -> AnalyticsEventSender:
    if (measurement_id := config.google_analytics_measurement_id) and (secret := config.google_analytics_api_secret):
        log.info("Use Google Analytics Event Sender.")
        sender = GoogleAnalyticsEventSender(client, measurement_id, secret)
        sender.event_handler = DomainEventToAnalyticsEventHandler(
            config.instance_id, domain_event_subscriber, sender, workspace_repo
        )
        return sender
    else:
        log.info("Analytics turned off.")
        return NoAnalyticsEventSender()
