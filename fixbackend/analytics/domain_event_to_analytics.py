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

from httpx import AsyncClient

from fixbackend.analytics import AnalyticsEventSender
from fixbackend.analytics.analytics_event_sender import GoogleAnalyticsEventSender, NoAnalyticsEventSender
from fixbackend.analytics.events import (
    AEUserRegistered,
    AEAccountDiscovered,
    AEAccountConfigured,
    AEAccountDeleted,
    AEAccountDegraded,
    AEWorkspaceCreated,
    AEInvitationAccepted,
    AEUserJoinedWorkspace,
    AEProductTierChanged,
    AESubscriptionCreated,
    AEUserLoggedIn,
    AEFailingBenchmarkChecksAlertSend,
    AEAccountNameChanged,
    AEBillingEntryCreated,
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
    ProductTierChanged,
    Event,
    AwsMarketplaceSubscriptionCreated,
    UserLoggedIn,
    FailingBenchmarkChecksAlertSend,
    BillingEntryCreated,
)
from fixbackend.domain_events.subscriber import DomainEventSubscriber
from fixbackend.workspaces.repository import WorkspaceRepository

log = logging.getLogger(__name__)


class DomainEventToAnalyticsEventHandler:
    def __init__(self, domain_event_subscriber: DomainEventSubscriber, sender: AnalyticsEventSender) -> None:
        self.sender = sender
        domain_event_subscriber.subscribe(UserRegistered, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(AwsAccountDiscovered, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(AwsAccountConfigured, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(AwsAccountDeleted, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(AwsAccountDegraded, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(CloudAccountNameChanged, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(WorkspaceCreated, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(InvitationAccepted, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(UserJoinedWorkspace, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(ProductTierChanged, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(AwsMarketplaceSubscriptionCreated, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(UserLoggedIn, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(FailingBenchmarkChecksAlertSend, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(BillingEntryCreated, self.handle, "domain_event_to_analytics")

    async def handle(self, event: Event) -> None:
        match event:
            case UserRegistered() as event:
                await self.sender.send(AEUserRegistered(event.user_id, event.tenant_id))
            case AwsAccountDiscovered() as event:
                user_id = await self.sender.user_id_from_workspace(event.tenant_id)
                await self.sender.send(AEAccountDiscovered(user_id, event.tenant_id, "aws"))
            case AwsAccountConfigured() as event:
                user_id = await self.sender.user_id_from_workspace(event.tenant_id)
                await self.sender.send(AEAccountConfigured(user_id, event.tenant_id, "aws"))
            case AwsAccountDeleted() as event:
                await self.sender.send(AEAccountDeleted(event.user_id, event.tenant_id, "aws"))
            case AwsAccountDegraded() as event:
                user_id = await self.sender.user_id_from_workspace(event.tenant_id)
                await self.sender.send(AEAccountDegraded(user_id, event.tenant_id, "aws", event.error))
            case CloudAccountNameChanged() as event:
                user_id = await self.sender.user_id_from_workspace(event.tenant_id)
                await self.sender.send(AEAccountNameChanged(user_id, event.tenant_id, event.cloud))
            case WorkspaceCreated() as event:
                await self.sender.send(AEWorkspaceCreated(event.user_id, event.workspace_id))
            case InvitationAccepted() as event:
                user_id = event.user_id or await self.sender.user_id_from_workspace(event.workspace_id)
                await self.sender.send(AEInvitationAccepted(user_id, event.workspace_id))
            case UserJoinedWorkspace() as event:
                await self.sender.send(AEUserJoinedWorkspace(event.user_id, event.workspace_id))
            case ProductTierChanged() as event:
                await self.sender.send(AEProductTierChanged(event.user_id, event.workspace_id, event.product_tier))
            case AwsMarketplaceSubscriptionCreated() as event:
                if ws_id := event.workspace_id:
                    await self.sender.send(AESubscriptionCreated(event.user_id, ws_id, "aws_marketplace"))
            case UserLoggedIn() as event:
                await self.sender.send(AEUserLoggedIn(event.user_id))
            case FailingBenchmarkChecksAlertSend() as event:
                user_id = await self.sender.user_id_from_workspace(event.workspace_id)
                await self.sender.send(
                    AEFailingBenchmarkChecksAlertSend(
                        user_id, event.workspace_id, event.benchmark, event.failed_checks_count_total
                    )
                )
            case BillingEntryCreated() as event:
                user_id = await self.sender.user_id_from_workspace(event.tenant_id)
                await self.sender.send(AEBillingEntryCreated(user_id, event.tenant_id, event.product_tier, event.usage))
            case _:
                log.info(f"Do not know how to handle event: {event}. Ignore.")


def analytics(
    config: Config,
    client: AsyncClient,
    domain_event_subscriber: DomainEventSubscriber,
    workspace_repo: WorkspaceRepository,
) -> AnalyticsEventSender:
    if (measurement_id := config.google_analytics_measurement_id) and (secret := config.google_analytics_api_secret):
        log.info("Use Google Analytics Event Sender.")
        sender = GoogleAnalyticsEventSender(client, measurement_id, secret, workspace_repo)
        sender.event_handler = DomainEventToAnalyticsEventHandler(domain_event_subscriber, sender)
        return sender
    else:
        log.info("Analytics turned off.")
        return NoAnalyticsEventSender()
