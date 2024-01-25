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
from datetime import timedelta
from logging import getLogger
from typing import Iterator, List, Optional

import cattrs
from attr import frozen
from fixcloudutils.redis.event_stream import RedisStreamPublisher, RedisStreamListener, MessageContext
from fixcloudutils.service import Service
from fixcloudutils.types import Json
from fixcloudutils.util import utc
from redis.asyncio import Redis

from fixbackend.auth.user_repository import UserRepository
from fixbackend.config import Config
from fixbackend.domain_events.events import TenantAccountsCollected
from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import WorkspaceId
from fixbackend.inventory.inventory_service import InventoryService, ReportSeverityIncluded
from fixbackend.inventory.schemas import SearchRequest, HistorySearch, HistoryChange
from fixbackend.logging_context import set_workspace_id
from fixbackend.notification.email.email_messages import EmailMessage
from fixbackend.notification.email.email_sender import (
    EmailSender,
    email_sender_from_config,
)
from fixbackend.notification.model import AlertingSetting
from fixbackend.notification.notification_provider_config_repo import (
    NotificationProviderConfigRepository,
    NotificationProvider,
)
from fixbackend.notification.workspace_alert_config_repo import WorkspaceAlertRepository
from fixbackend.types import AsyncSessionMaker
from fixbackend.workspaces.repository import WorkspaceRepository

log = getLogger(__name__)


@frozen
class Alert:
    workspace_id: WorkspaceId
    channel: str


@frozen
class VulnerableResource:
    id: str
    kind: str
    name: Optional[str] = None
    cloud: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    zone: Optional[str] = None


@frozen
class VulnerableResourcesDetected(Alert):
    benchmark: str
    severity: str
    count: int
    examples: List[VulnerableResource]


class NotificationService(Service):
    def __init__(
        self,
        config: Config,
        workspace_repository: WorkspaceRepository,
        graphdb_access: GraphDatabaseAccessManager,
        user_repository: UserRepository,
        inventory_service: InventoryService,
        readwrite_redis: Redis,
        session_maker: AsyncSessionMaker,
    ) -> None:
        self.email_sender: EmailSender = email_sender_from_config(config)
        self.workspace_repository = workspace_repository
        self.graphdb_access = graphdb_access
        self.user_repository = user_repository
        self.inventory_service = inventory_service
        self.alert_publisher = RedisStreamPublisher(readwrite_redis, "fix_alerts", "fixbackend")
        self.alert_listener = RedisStreamListener(
            readwrite_redis,
            "fix_alerts",
            "fixbackend",
            config.instance_id,
            self._send_alert,
            consider_failed_after=timedelta(seconds=180),
            batch_size=50,
        )
        self.provider_config_repo = NotificationProviderConfigRepository(session_maker)
        self.workspace_alert_repo = WorkspaceAlertRepository(session_maker)

    async def send_email(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        html: Optional[str],
    ) -> None:
        """Send an email to the given address."""
        await self.email_sender.send_email(to=[to], subject=subject, text=text, html=html)

    async def send_message(self, *, to: str, message: EmailMessage) -> None:
        await self.send_email(to=to, subject=message.subject(), text=message.text(), html=message.html())

    async def send_message_to_workspace(
        self,
        *,
        workspace_id: WorkspaceId,
        message: EmailMessage,
    ) -> None:
        set_workspace_id(workspace_id)
        workspace = await self.workspace_repository.get_workspace(workspace_id)
        if not workspace:
            log.error(f"Workspace {workspace_id} not found")
            return

        emails = [user.email for user in await self.user_repository.get_by_ids(workspace.all_users())]

        def batch(items: List[str], n: int = 50) -> Iterator[List[str]]:
            current_batch: List[str] = []
            for item in items:
                current_batch.append(item)
                if len(current_batch) == n:
                    yield current_batch
                    current_batch = []
            if current_batch:
                yield current_batch

        batches = list(batch(emails))

        for email_batch in batches:
            await self.email_sender.send_email(
                to=email_batch, subject=message.subject(), text=message.text(), html=message.html()
            )

    async def update_notification_provider_config(
        self, workspace_id: WorkspaceId, provider: NotificationProvider, name: str, config: Json
    ) -> None:
        await self.provider_config_repo.update_messaging_config_for_workspace(workspace_id, provider, name, config)

    async def _send_alert(self, message: Json, context: MessageContext) -> None:
        if context.kind != "vulnerable_resources_detected":
            raise ValueError(f"Unexpected message kind {context.kind}")
        alert = cattrs.structure(message, VulnerableResourcesDetected)
        match alert.channel:
            case "discord":
                pass
            case "slack":
                pass
            case "email":
                pass
            case "pagerduty":
                pass

    async def alert_on_changed(self, collected: TenantAccountsCollected) -> None:
        set_workspace_id(collected.tenant_id)
        earliest_started_at = min([a.started_at for a in collected.cloud_accounts.values()], default=utc())
        task_ids = ",".join(a.task_id for a in collected.cloud_accounts.values() if a.task_id is not None)
        now = utc()

        async def send_alert_for(access: GraphDatabaseAccess, benchmark: str, setting: AlertingSetting) -> None:
            included_severities = ",".join(ReportSeverityIncluded.get(setting.severity, ["none"]))
            issue = f"benchmarks[]=={benchmark} and run_id in [{task_ids}] and severity in [{included_severities}]"
            request = SearchRequest(
                query=f"/security.has_issues==true and /security.issues[].{{{issue}}}",
                history=HistorySearch(after=earliest_started_at, before=now, change=HistoryChange.node_vulnerable),
                limit=25,
                count=True,
            )
            result = await self.inventory_service.search_table(access, request)
            vulnerable_resources = [
                cattrs.structure(e["row"], VulnerableResource) async for e in result if "row" in e  # type: ignore
            ]
            if vulnerable_resources:
                for channel in setting.channels:
                    alert = VulnerableResourcesDetected(
                        workspace_id=collected.tenant_id,
                        channel=channel,
                        benchmark=benchmark,
                        severity=setting.severity,
                        count=int(result.context.get("total-count", len(vulnerable_resources))),
                        examples=vulnerable_resources,
                    )
                    await self.alert_publisher.publish("vulnerable_resources_detected", cattrs.unstructure(alert))

        # make sure we have collected some resources, have a non-empty alert config and access to the graph db
        if sum(a.scanned_resources for a in collected.cloud_accounts.values()) > 0:
            if (
                (cfg := await self.workspace_alert_repo.alerting_for(collected.tenant_id))
                and (non_empty_alerts := cfg.non_empty_alerts())
                and (access := await self.graphdb_access.get_database_access(collected.tenant_id))
            ):
                for benchmark, setting in non_empty_alerts.items():
                    await send_alert_for(access, benchmark, setting)
