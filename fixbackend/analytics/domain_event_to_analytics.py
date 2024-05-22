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
from typing import List

from httpx import AsyncClient

from fixbackend.analytics import AnalyticsEventSender
from fixbackend.analytics.analytics_event_sender import (
    GoogleAnalyticsEventSender,
    NoAnalyticsEventSender,
    PostHogEventSender,
    MultiAnalyticsEventSender,
)
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
    CloudAccountConfigured,
    CloudAccountDeleted,
    AwsAccountDegraded,
    CloudAccountNameChanged,
    WorkspaceCreated,
    InvitationAccepted,
    UserJoinedWorkspace,
    ProductTierChanged,
    Event,
    SubscriptionCreated,
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
        domain_event_subscriber.subscribe(CloudAccountConfigured, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(CloudAccountDeleted, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(AwsAccountDegraded, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(CloudAccountNameChanged, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(WorkspaceCreated, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(InvitationAccepted, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(UserJoinedWorkspace, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(ProductTierChanged, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(SubscriptionCreated, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(UserLoggedIn, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(FailingBenchmarkChecksAlertSend, self.handle, "domain_event_to_analytics")
        domain_event_subscriber.subscribe(BillingEntryCreated, self.handle, "domain_event_to_analytics")

    async def handle(self, event: Event) -> None:
        match event:
            case UserRegistered() as e:
                await self.sender.send(AEUserRegistered(e.id, e.created_at, e.user_id, e.tenant_id, e.email))
            case AwsAccountDiscovered() as e:
                user_id = await self.sender.user_id_from_workspace(e.tenant_id)
                await self.sender.send(AEAccountDiscovered(e.id, e.created_at, user_id, e.tenant_id, "aws"))
            case CloudAccountConfigured() as e:
                user_id = await self.sender.user_id_from_workspace(e.tenant_id)
                await self.sender.send(AEAccountConfigured(e.id, e.created_at, user_id, e.tenant_id, e.cloud))
            case CloudAccountDeleted() as e:
                await self.sender.send(AEAccountDeleted(e.id, e.created_at, e.user_id, e.tenant_id, e.cloud))
            case AwsAccountDegraded() as e:
                user_id = await self.sender.user_id_from_workspace(e.tenant_id)
                await self.sender.send(AEAccountDegraded(e.id, e.created_at, user_id, e.tenant_id, "aws", e.error))
            case CloudAccountNameChanged() as e:
                user_id = await self.sender.user_id_from_workspace(e.tenant_id)
                await self.sender.send(AEAccountNameChanged(e.id, e.created_at, user_id, e.tenant_id, e.cloud))
            case WorkspaceCreated() as e:
                await self.sender.send(
                    AEWorkspaceCreated(e.id, e.created_at, e.user_id, e.workspace_id, e.name, e.slug)
                )
            case InvitationAccepted() as e:
                user_id = e.user_id or await self.sender.user_id_from_workspace(e.workspace_id)
                await self.sender.send(AEInvitationAccepted(e.id, e.created_at, user_id, e.workspace_id))
            case UserJoinedWorkspace() as e:
                await self.sender.send(AEUserJoinedWorkspace(e.id, e.created_at, e.user_id, e.workspace_id))
            case ProductTierChanged() as e:
                await self.sender.send(
                    AEProductTierChanged(e.id, e.created_at, e.user_id, e.workspace_id, e.product_tier)
                )
            case SubscriptionCreated() as e:
                if ws_id := e.workspace_id:
                    await self.sender.send(
                        AESubscriptionCreated(e.id, e.created_at, e.user_id, ws_id, "aws_marketplace")
                    )
            case UserLoggedIn() as e:
                await self.sender.send(AEUserLoggedIn(e.id, e.created_at, e.user_id))
            case FailingBenchmarkChecksAlertSend() as e:
                user_id = await self.sender.user_id_from_workspace(e.workspace_id)
                await self.sender.send(
                    AEFailingBenchmarkChecksAlertSend(
                        e.id, e.created_at, user_id, e.workspace_id, e.benchmark, e.failed_checks_count_total
                    )
                )
            case BillingEntryCreated() as e:
                user_id = await self.sender.user_id_from_workspace(e.tenant_id)
                await self.sender.send(
                    AEBillingEntryCreated(e.id, e.created_at, user_id, e.tenant_id, e.product_tier, e.usage)
                )
            case _:
                log.info(f"Do not know how to handle event: {event}. Ignore.")


def analytics(
    config: Config,
    client: AsyncClient,
    domain_event_subscriber: DomainEventSubscriber,
    workspace_repo: WorkspaceRepository,
) -> AnalyticsEventSender:
    senders: List[AnalyticsEventSender] = []
    if (measurement_id := config.google_analytics_measurement_id) and (secret := config.google_analytics_api_secret):
        log.info("Use Google Analytics Event Sender.")
        senders.append(GoogleAnalyticsEventSender(client, measurement_id, secret, workspace_repo))
    if api_key := config.posthog_api_key:
        log.info("Use Posthog Event Sender.")
        senders.append(PostHogEventSender(api_key, workspace_repo))
    if len(senders) == 0:
        log.info("Analytics turned off.")
        senders.append(NoAnalyticsEventSender())
    sender = MultiAnalyticsEventSender(senders)
    sender.event_handler = DomainEventToAnalyticsEventHandler(domain_event_subscriber, sender)
    return sender
