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
from collections import defaultdict
from datetime import timedelta, datetime
from itertools import islice
from logging import getLogger
from typing import List, Optional, Dict, Union, Set
from urllib.parse import urlencode

import cattrs
from fixcloudutils.redis.event_stream import RedisStreamPublisher, RedisStreamListener, MessageContext
from fixcloudutils.service import Service
from fixcloudutils.types import Json
from fixcloudutils.util import utc, utc_str
from httpx import AsyncClient

from fixbackend.auth.user_repository import UserRepository
from fixbackend.config import Config
from fixbackend.domain_events.events import (
    TenantAccountsCollected,
    FailingBenchmarkChecksAlertSend,
    UserJoinedWorkspace,
    AlertNotificationSetupUpdated,
)
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.domain_events.subscriber import DomainEventSubscriber
from fixbackend.fix_jwt import JwtService
from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import WorkspaceId, TaskId, BenchmarkName, ReportSeverity, NotificationProvider, NodeId, UserId
from fixbackend.inventory.inventory_service import InventoryService, ReportSeverityIncluded, ReportSeverityPriority
from fixbackend.inventory.inventory_schemas import SearchRequest, HistorySearch, HistoryChange
from fixbackend.logging_context import set_workspace_id
from fixbackend.notification.discord.discord_notification import DiscordNotificationSender
from fixbackend.notification.email.email_messages import EmailMessage, UserJoinedWorkspaceMail
from fixbackend.notification.email.email_notification import EmailNotificationSender
from fixbackend.notification.email.email_sender import (
    EmailSender,
    email_sender_from_config,
)
from fixbackend.notification.model import (
    WorkspaceAlert,
    AlertSender,
    AlertOnChannel,
    FailingBenchmarkChecksDetected,
    VulnerableResource,
    FailedBenchmarkCheck,
)
from fixbackend.notification.notification_provider_config_repo import NotificationProviderConfigRepository
from fixbackend.notification.opsgenie.opsgenie_notification import OpsgenieNotificationSender
from fixbackend.notification.pagerduty.pagerduty_notification import PagerDutyNotificationSender
from fixbackend.notification.slack.slack_notification import SlackNotificationSender
from fixbackend.notification.teams.teams_notification import TeamsNotificationSender
from fixbackend.notification.workspace_alert_config_repo import WorkspaceAlertRepository
from fixbackend.types import AsyncSessionMaker
from fixbackend.types import Redis
from fixbackend.utils import md5
from fixbackend.workspaces.repository import WorkspaceRepository

log = getLogger(__name__)


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
        http_client: AsyncClient,
        domain_event_sender: DomainEventPublisher,
        domain_event_subscriber: DomainEventSubscriber,
        jwt_service: JwtService,
        handle_events: bool = True,
    ) -> None:
        self.config = config
        self.email_sender: EmailSender = email_sender_from_config(config, jwt_service)
        self.workspace_repository = workspace_repository
        self.graphdb_access = graphdb_access
        self.user_repository = user_repository
        self.inventory_service = inventory_service
        self.inventory_client = inventory_service.client
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
        self.alert_sender: Dict[NotificationProvider, AlertSender] = {
            NotificationProvider.discord: DiscordNotificationSender(http_client),
            NotificationProvider.slack: SlackNotificationSender(http_client),
            NotificationProvider.teams: TeamsNotificationSender(http_client),
            NotificationProvider.pagerduty: PagerDutyNotificationSender(http_client),
            NotificationProvider.email: EmailNotificationSender(self.email_sender),
            NotificationProvider.opsgenie: OpsgenieNotificationSender(http_client),
        }
        self.handle_events = handle_events
        self.domain_event_sender = domain_event_sender
        if handle_events:
            domain_event_subscriber.subscribe(TenantAccountsCollected, self.alert_on_changed, "NotificationService")
            domain_event_subscriber.subscribe(
                UserJoinedWorkspace, self._send_welcome_email_to_new_user, "NotificationService"
            )

    async def start(self) -> None:
        if self.handle_events:
            await self.alert_listener.start()
            await self.alert_publisher.start()

    async def stop(self) -> None:
        if self.handle_events:
            await self.alert_publisher.stop()
            await self.alert_listener.stop()

    async def send_email(self, *, to: str, subject: str, text: str, html: Optional[str]) -> None:
        await self.email_sender.send_email(to=to, subject=subject, text=text, html=html)

    async def send_message(self, *, to: str, message: EmailMessage) -> None:
        await self.send_email(to=to, subject=message.subject(), text=message.text(), html=message.html())

    async def send_message_to_workspace(self, *, workspace_id: WorkspaceId, message: EmailMessage) -> None:
        await self.send_email_to_workspace(
            workspace_id=workspace_id, subject=message.subject(), text=message.text(), html=message.html()
        )

    async def send_email_to_workspace(
        self, *, workspace_id: WorkspaceId, subject: str, text: str, html: Optional[str]
    ) -> None:
        set_workspace_id(workspace_id)
        workspace = await self.workspace_repository.get_workspace(workspace_id)
        if not workspace:
            log.error(f"Workspace {workspace_id} not found")
            return

        emails = [user.email for user in await self.user_repository.get_by_ids(workspace.all_users())]
        for email in emails:
            try:
                await self.email_sender.send_email(to=email, subject=subject, text=text, html=html)
            except Exception as e:
                log.error(f"Failed to send message to workspace {workspace_id}: {e}")

    async def list_notification_provider_configs(self, workspace_id: WorkspaceId) -> Dict[str, Json]:
        configs = await self.provider_config_repo.all_messaging_configs_for_workspace(workspace_id)
        return {c.provider: {"name": c.name, **c.readable_config()} for c in configs}

    async def delete_notification_provider_config(
        self, workspace_id: WorkspaceId, provider: NotificationProvider
    ) -> None:
        if alerting := await self.workspace_alert_repo.alerting_for(workspace_id):
            changed = False
            for benchmark, alert in alerting.alerts.items():
                if provider in alert.channels:
                    alert.channels.remove(provider)
                    changed = True
            if changed:
                await self.workspace_alert_repo.set_alerting_for_workspace(alerting)
        await self.provider_config_repo.delete_messaging_config_for_workspace(workspace_id, provider)

    async def update_notification_provider_config(
        self, workspace_id: WorkspaceId, user_id: UserId, provider: NotificationProvider, name: str, config: Json
    ) -> None:
        await self.domain_event_sender.publish(AlertNotificationSetupUpdated(workspace_id, user_id, provider))
        await self.provider_config_repo.update_messaging_config_for_workspace(workspace_id, provider, name, config)

    async def alerting_for(self, workspace_id: WorkspaceId) -> Optional[WorkspaceAlert]:
        return await self.workspace_alert_repo.alerting_for(workspace_id)

    async def update_alerting_for(self, alert: WorkspaceAlert) -> Union[None, WorkspaceAlert]:
        # validate the setting:
        # - all benchmark names must exist
        # - all channels must be known
        if access := await self.graphdb_access.get_database_access(alert.workspace_id):
            benchmark_ids: Set[str] = set(await self.inventory_client.benchmarks(access, ids_only=True))  # type: ignore
            for benchmark, setting in alert.alerts.items():
                if benchmark not in benchmark_ids:
                    raise ValueError(f"Benchmark {benchmark} not found")
                for channel in setting.channels:
                    if channel not in NotificationProvider:
                        raise ValueError(f"Unknown channel {channel}")
            return await self.workspace_alert_repo.set_alerting_for_workspace(alert)
        raise ValueError(f"Workspace {alert.workspace_id} does not have GraphDbAccess?")

    async def _send_alert(self, message: Json, context: MessageContext) -> None:
        if context.kind != "vulnerable_resources_detected":
            raise ValueError(f"Unexpected message kind {context.kind}")
        alert_on = AlertOnChannel.from_json(message)
        alert = alert_on.alert
        set_workspace_id(alert.workspace_id)
        if (sender := self.alert_sender.get(alert_on.channel)) and (
            cfg := await self.provider_config_repo.get_messaging_config_for_workspace(
                alert.workspace_id, alert_on.channel
            )
        ):
            await sender.send_alert(alert, cfg)

    async def _load_alert(
        self,
        access: GraphDatabaseAccess,
        benchmark: BenchmarkName,
        task_ids: List[TaskId],
        severity: ReportSeverity,
        after: datetime,
        before: datetime,
    ) -> Optional[FailingBenchmarkChecksDetected]:
        included_severities = ",".join(ReportSeverityIncluded.get(severity, ["none"]))
        tsk_ids = ",".join(task_ids)
        issue = f"benchmarks[]=={benchmark} and severity in [{included_severities}]"
        query = (
            f"/security.has_issues==true and /security.run_id in [{tsk_ids}] and /diff.node_vulnerable[].{{{issue}}}"
        )
        aggregate = "/diff.node_vulnerable[].check, /diff.node_vulnerable[].severity, /diff.node_vulnerable[].benchmarks[] as benchmark : sum(1) as count"  # noqa: E501
        failing_checks: Dict[str, str] = {}
        failing_resources_count: Dict[str, int] = defaultdict(int)
        total_failed_checks = 0
        change = [HistoryChange.node_vulnerable, HistoryChange.node_compliant]
        async with self.inventory_client.search_history(
            access, f"search {query} | aggregate {aggregate}", before=before, after=after, change=change
        ) as result:
            async for agg in result:
                if (
                    (count := agg.get("count"))
                    and (group := agg.get("group"))
                    and (check := group.get("check"))
                    and (severity := group.get("severity"))
                    and (bench := group.get("benchmark"))
                    and bench == benchmark
                ):
                    total_failed_checks += 1
                    failing_checks[check] = severity
                    failing_resources_count[check] = count

        if total_failed_checks > 0:
            # pick examples for the top 5 checks
            srt = sorted(failing_checks.items(), key=lambda x: ReportSeverityPriority[x[1]], reverse=True)
            top_checks = [k for k, _ in islice(srt, 5)]
            # load examples for the top 5 checks
            example_resources: Dict[str, List[VulnerableResource]] = defaultdict(list)
            example_count = 0
            async with self.inventory_client.execute_single(
                access,
                f"history --before {utc_str(before)} --after {utc_str(after)} --change node_vulnerable --change node_compliant /security.has_issues==true and /diff.node_vulnerable[].{{check in [{','.join(top_checks)}] and {issue}}} | "  # noqa
                f"jq --no-rewrite '{{id:.id, kind:.reported.kind, name:.reported.name, cloud:.ancestors.cloud.reported.name, account:.ancestors.account.reported.name, region:.ancestors.region.reported.name, checks: [ .security.issues[] | select(.benchmarks != null and .benchmarks[] == \"{benchmark}\") | .check ]}}'",  # noqa
            ) as result:
                async for node in result:
                    if isinstance(node, dict):
                        for check in node.get("checks", []):
                            examples = example_resources[check]
                            if check in top_checks and len(examples) < 3:
                                resource = cattrs.structure(node, VulnerableResource)
                                # the ui link does not come from the inventory and needs to be computed explicitly
                                resource.ui_link = f"{self.config.service_base_url}/inventory/resource-detail/{resource.id}?{urlencode(dict(name=resource.name))}#{access.workspace_id}"  # noqa: E501
                                examples.append(resource)
                                example_count += 1
                                if example_count == 25:
                                    break
            # load definition of top checks
            top_check_defs = [
                FailedBenchmarkCheck(cid, title, sev, failing_resources_count[cid], example_resources[cid])
                for c in await self.inventory_client.checks(access, check_ids=top_checks)
                if (cid := c.get("id")) and (title := c.get("title")) and (sev := c.get("severity"))
            ]
            # ui link
            ui_link = SearchRequest(
                query=query, history=HistorySearch(after=after, before=before, changes=change)
            ).ui_link(self.config.service_base_url, access.workspace_id)
            return FailingBenchmarkChecksDetected(
                id=md5(benchmark, *task_ids),
                workspace_id=access.workspace_id,
                benchmark=benchmark,
                severity=top_check_defs[0].severity if top_checks else severity,
                failed_checks_count_total=total_failed_checks,
                examples=top_check_defs,
                ui_link=ui_link,
            )
        return None

    async def alert_on_changed(self, collected: TenantAccountsCollected) -> None:
        set_workspace_id(collected.tenant_id)
        earliest_started_at = min([a.started_at for a in collected.cloud_accounts.values()], default=utc())
        task_ids = [a.task_id for a in collected.cloud_accounts.values() if a.task_id is not None]
        now = utc()

        # make sure we have collected some resources, have a non-empty alert config and access to the graph db
        if sum(a.scanned_resources for a in collected.cloud_accounts.values()) > 0:
            if (
                (cfg := await self.workspace_alert_repo.alerting_for(collected.tenant_id))
                and (non_empty_alerts := cfg.non_empty_alerts())
                and (access := await self.graphdb_access.get_database_access(collected.tenant_id))
            ):
                for benchmark, setting in non_empty_alerts.items():
                    if alert := await self._load_alert(
                        access, benchmark, task_ids, setting.severity, earliest_started_at, now
                    ):
                        for channel in setting.channels:
                            await self.alert_publisher.publish(
                                "vulnerable_resources_detected", AlertOnChannel(alert, channel).to_json()
                            )
                        await self.domain_event_sender.publish(
                            FailingBenchmarkChecksAlertSend(
                                collected.tenant_id,
                                benchmark,
                                alert.severity,
                                alert.failed_checks_count_total,
                                setting.channels,
                            )
                        )

    async def send_test_alert(self, workspace_id: WorkspaceId, provider: NotificationProvider) -> None:
        if access := await self.graphdb_access.get_database_access(workspace_id):
            ui_link = SearchRequest(query="all").ui_link(self.config.service_base_url, access.workspace_id)
            now = utc()
            resource = VulnerableResource(id=NodeId("example"), name="example", kind="account", ui_link=ui_link)
            alert = FailingBenchmarkChecksDetected(
                id=md5("test", workspace_id),
                workspace_id=workspace_id,
                benchmark=BenchmarkName("Example Benchmark"),
                severity="info",
                failed_checks_count_total=2,
                examples=[
                    FailedBenchmarkCheck("test-1", "Example Check Only For Testing!", "info", 1, [resource]),
                    FailedBenchmarkCheck("test-2", "Please Ignore.", "medium", 1, [resource]),
                ],
                ui_link=ui_link,
            )
            await self._send_alert(
                AlertOnChannel(alert, provider).to_json(),
                MessageContext("test-message", "vulnerable_resources_detected", "fixbackend", now, now),
            )

        else:
            log.error(f"Workspace {workspace_id} does not have GraphDbAccess?")

    async def _send_welcome_email_to_new_user(self, event: UserJoinedWorkspace) -> None:
        if (user := await self.user_repository.get(event.user_id)) and (
            workspace := await self.workspace_repository.get_workspace(event.workspace_id)
        ):
            await self.send_message(to=user.email, message=UserJoinedWorkspaceMail(user=user, workspace=workspace))
