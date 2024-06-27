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
import asyncio
import json
import math
import uuid
from collections import defaultdict
from datetime import timedelta
from functools import partial
from hmac import compare_digest
from logging import getLogger
from typing import Any, Dict, List, Optional, Union

import boto3
from attrs import evolve, frozen
from fixcloudutils.asyncio.periodic import Periodic
from fixcloudutils.redis.event_stream import Backoff, DefaultBackoff, Json, MessageContext, RedisStreamListener
from fixcloudutils.redis.pub_sub import RedisPubSubPublisher
from fixcloudutils.service import Service
from fixcloudutils.util import utc, uuid_str
from httpx import AsyncClient

from fixbackend.analytics import AnalyticsEventSender
from fixbackend.analytics.events import (
    AEFirstAccountCollectFinished,
    AEFirstWorkspaceCollectFinished,
    AEWorkspaceCollectFinished,
)
from fixbackend.cloud_accounts.account_setup import AssumeRoleResults, AwsAccountSetupHelper
from fixbackend.cloud_accounts.models import (
    AwsCloudAccess,
    AzureCloudAccess,
    CloudAccess,
    CloudAccount,
    CloudAccountState,
    CloudAccountStates,
    GcpCloudAccess,
)
from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.cloud_accounts.service import CloudAccountService, WrongExternalId
from fixbackend.config import Config, Free, ProductTierSettings
from fixbackend.dispatcher.next_run_repository import NextRunRepository
from fixbackend.domain_events import DomainEventsStreamName
from fixbackend.domain_events.events import (
    CloudAccountConfigured,
    CloudAccountDegraded,
    CloudAccountDeleted,
    CloudAccountDiscovered,
    DegradationReason,
    SubscriptionCancelled,
    ProductTierChanged,
    CloudAccountActiveToggled,
    CloudAccountNameChanged,
    CloudAccountScanToggled,
    SubscriptionCreated,
    TenantAccountsCollectFailed,
    TenantAccountsCollected,
)
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.errors import NotAllowed, ResourceNotFound, WrongState
from fixbackend.ids import (
    AwsRoleName,
    AzureSubscriptionCredentialsId,
    CloudAccountId,
    CloudAccountName,
    CloudNames,
    ExternalId,
    FixCloudAccountId,
    GcpServiceAccountKeyId,
    UserCloudAccountName,
    UserId,
    WorkspaceId,
)
from fixbackend.logging_context import set_cloud_account_id, set_fix_cloud_account_id, set_workspace_id
from fixbackend.notification.email import email_messages as email
from fixbackend.notification.notification_service import NotificationService
from fixbackend.sqs import SQSRawListener
from fixbackend.types import Redis
from fixbackend.utils import uid
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository

log = getLogger(__name__)


@frozen
class UnknownCloud:
    cloud: str


@frozen
class UnknownAccessType:
    access: CloudAccess


@frozen
class WrongAccountState:
    state: CloudAccountState


@frozen
class CantAssumeRole:
    retry_limit_reached: bool


@frozen
class RoleNameMissing:
    pass


@frozen
class ConcurrentUpdate:
    pass


ConfigurationFailure = Union[
    UnknownCloud,
    UnknownAccessType,
    WrongAccountState,
    CantAssumeRole,
    RoleNameMissing,
    ConcurrentUpdate,
]


class CloudAccountServiceImpl(CloudAccountService, Service):
    def __init__(
        self,
        *,
        workspace_repository: WorkspaceRepository,
        cloud_account_repository: CloudAccountRepository,
        next_run_repository: NextRunRepository,
        pubsub_publisher: RedisPubSubPublisher,
        domain_event_publisher: DomainEventPublisher,
        readwrite_redis: Redis,
        config: Config,
        account_setup_helper: AwsAccountSetupHelper,
        dispatching: bool,
        http_client: AsyncClient,
        boto_session: boto3.Session,
        cf_stack_queue_url: Optional[str] = None,
        notification_service: NotificationService,
        analytics_event_sender: AnalyticsEventSender,
    ) -> None:
        self.workspace_repository = workspace_repository
        self.cloud_account_repository = cloud_account_repository
        self.next_run_repository = next_run_repository
        self.pubsub_publisher = pubsub_publisher
        self.domain_events = domain_event_publisher
        self.notification_service = notification_service
        self.analytics_event_sender = analytics_event_sender
        backoff_config: Dict[str, Backoff] = defaultdict(lambda: DefaultBackoff)
        backoff_config[CloudAccountDiscovered.kind] = Backoff(
            base_delay=5,
            maximum_delay=10,
            retries=8,
            log_failed_attempts=False,
        )
        if dispatching:
            self.periodic: Optional[Periodic] = Periodic(
                "configure_discovered_accounts", self.configure_discovered_accounts, timedelta(minutes=1)
            )
            # dispatcher should not handle domain events or CF stack events
            self.domain_event_listener: Optional[RedisStreamListener] = None
            self.cf_listener: Optional[SQSRawListener] = None
        else:
            self.periodic = None
            self.domain_event_listener = RedisStreamListener(
                readwrite_redis,
                DomainEventsStreamName,
                group="fixbackend-cloudaccountservice-domain",
                listener=config.instance_id,
                message_processor=self.process_domain_event,
                consider_failed_after=timedelta(minutes=5),
                batch_size=config.cloud_account_service_event_parallelism,
                parallelism=config.cloud_account_service_event_parallelism,
                backoff=backoff_config,
            )
            self.cf_listener = (
                SQSRawListener(
                    session=boto_session,
                    queue_url=cf_stack_queue_url,
                    message_processor=self.process_cf_stack_event,
                    consider_failed_after=timedelta(minutes=5),
                    max_nr_of_messages_in_one_batch=1,
                    wait_for_new_messages_to_arrive=timedelta(seconds=20),
                )
                if cf_stack_queue_url
                else None
            )
        self.instance_id = config.instance_id
        self.account_setup_helper = account_setup_helper
        self.dispatching = dispatching
        self.fast_lane_timeout = timedelta(minutes=1)
        self.become_degraded_timeout = timedelta(minutes=15)
        self.http_client = http_client

    async def start(self) -> Any:
        if self.domain_event_listener:
            await self.domain_event_listener.start()
        if self.periodic:
            await self.periodic.start()
        if self.cf_listener:
            await self.cf_listener.start()

    async def stop(self) -> Any:
        if self.cf_listener:
            await self.cf_listener.stop()
        if self.periodic:
            await self.periodic.stop()
        if self.domain_event_listener:
            await self.domain_event_listener.stop()

    async def process_cf_stack_event(self, message: Json) -> Optional[CloudAccount]:
        log.info(f"Received CF stack event: {message}")

        def mark_failed() -> None:
            if listener := self.cf_listener:
                listener.mark_failed()

        async def send_response(
            msg: Json, physical_resource_id: Optional[str] = None, error_message: Optional[str] = None
        ) -> None:
            try:
                physical_resource_id = physical_resource_id or msg["PhysicalResourceId"]
                request_id = msg["RequestId"]
                logical_resource_id = msg["LogicalResourceId"]
                response_url = msg["ResponseURL"]
                resource_properties = msg["ResourceProperties"]
                role_name = AwsRoleName(resource_properties["RoleName"])
                stack_id = resource_properties["StackId"]
            except Exception as e:  # pragma: no cover
                log.warning(f"Not enough data to inform CF: {msg}. Error: {e}")
                mark_failed()
                return None

            # Signal CF that we're done
            response = await self.http_client.put(
                response_url,
                json={
                    "Status": "FAILURE" if error_message else "SUCCESS",
                    "Reason": error_message or "OK",
                    "LogicalResourceId": logical_resource_id,
                    "PhysicalResourceId": physical_resource_id,
                    "StackId": stack_id,
                    "RequestId": request_id,
                    "Data": {"RoleName": role_name},
                },
            )
            if response.is_error:
                raise RuntimeError(f"Failed to signal CF that we're done: {response}")

        async def handle_stack_created(msg: Json) -> Optional[CloudAccount]:
            try:
                resource_properties = msg["ResourceProperties"]
                workspace_id = WorkspaceId(uuid.UUID(resource_properties["WorkspaceId"]))
                external_id = ExternalId(uuid.UUID(resource_properties["ExternalId"]))
                role_name = AwsRoleName(resource_properties["RoleName"])
                stack_id = resource_properties["StackId"]
                assert stack_id.startswith("arn:aws:cloudformation:")
                assert stack_id.count(":") == 5
                account_id = CloudAccountId(stack_id.split(":")[4])
            except Exception as e:  # pragma: no cover
                log.warning(f"Received invalid CF stack create event: {msg}. Error: {e}")
                mark_failed()
                await send_response(msg, str(uid()), "Invalid format for CF stack create/update event")
                return None
            # Create/Update the account on our side
            set_workspace_id(workspace_id)
            set_cloud_account_id(account_id)
            account = await self.create_aws_account(
                workspace_id=workspace_id,
                account_id=account_id,
                role_name=role_name,
                external_id=external_id,
                account_name=None,
            )
            # Signal to CF that we're done
            await send_response(msg, str(account.id))
            return account

        async def handle_stack_deleted(msg: Json) -> Optional[CloudAccount]:
            try:
                resource_properties = msg["ResourceProperties"]
                role_name = AwsRoleName(resource_properties["RoleName"])
                external_id = ExternalId(uuid.UUID(resource_properties["ExternalId"]))
                cloud_account_id = FixCloudAccountId(uuid.UUID(msg["PhysicalResourceId"]))
            except Exception as e:  # pragma: no cover
                log.warning(f"Received invalid CF stack delete event: {msg}. Error: {e}")
                mark_failed()
                await send_response(msg, str(uid()), "Invalid format for CF stack delete event")
                return None
            if (
                (account := await self.cloud_account_repository.get(cloud_account_id))
                and isinstance(access := account.state.cloud_access(), AwsCloudAccess)
                # also make sure the stack refers to the same role and external id
                and access.role_name == role_name
                and access.external_id == external_id
            ):
                account = await self.__degrade_account(
                    FixCloudAccountId(cloud_account_id),
                    "CloudformationStack deleted",
                    reason=DegradationReason.stack_deleted,
                )
            await send_response(msg, str(cloud_account_id))
            return account

        try:
            body = json.loads(message["Body"])
            kind = body["RequestType"]
            match kind:
                case "Create":
                    return await handle_stack_created(body)
                case "Delete":
                    return await handle_stack_deleted(body)
                case "Update":
                    return await handle_stack_created(body)
                case _:  # pragma: no cover
                    log.info(f"Received a CF stack event that is currently not handled. Ignore. {kind}")
                    await send_response(message)  # still try to acknowledge the message
                    return None
        except Exception as e:  # pragma: no cover
            log.warning(f"Received invalid CF stack event: {message}. Error: {e}")
            mark_failed()
            return None

    async def process_domain_event(self, message: Json, context: MessageContext) -> None:
        log.info(f"Received domain event of kind {context.kind}: {message}")

        async def send_pub_sub_message(
            e: Union[
                CloudAccountDegraded,
                CloudAccountDiscovered,
                CloudAccountDeleted,
                CloudAccountConfigured,
                TenantAccountsCollected,
            ]
        ) -> None:
            msg = e.to_json()
            msg.pop("tenant_id", None)
            await self.pubsub_publisher.publish(kind=e.kind, message=msg, channel=f"tenant-events::{e.tenant_id}")

        async with asyncio.timeout(10):
            match context.kind:
                case TenantAccountsCollected.kind:
                    event = TenantAccountsCollected.from_json(message)

                    accounts = await self.cloud_account_repository.list(list(event.cloud_accounts.keys()))
                    collected_accounts = [account for account in accounts if account.id in event.cloud_accounts]
                    first_workspace_collect = all(account.last_scan_started_at is None for account in accounts)
                    first_account_collect = any(account.last_scan_started_at is None for account in collected_accounts)

                    set_workspace_id(event.tenant_id)
                    for account_id, collect_info in event.cloud_accounts.items():
                        set_fix_cloud_account_id(account_id)
                        set_cloud_account_id(collect_info.account_id)

                        def compute_failed_scan_count(acc: CloudAccount) -> int:
                            if collect_info.scanned_resources < 50:
                                return acc.failed_scan_count + 1
                            else:
                                return 0

                        updated = await self.cloud_account_repository.update(
                            account_id,
                            lambda acc: evolve(
                                acc,
                                last_scan_duration_seconds=collect_info.duration_seconds,
                                last_scan_resources_scanned=collect_info.scanned_resources,
                                last_scan_started_at=collect_info.started_at,
                                next_scan=event.next_run,
                                failed_scan_count=compute_failed_scan_count(acc),
                                last_task_id=collect_info.task_id,
                            ),
                        )

                        if updated.failed_scan_count > 3:
                            await self.__degrade_account(
                                updated.id, "Too many consecutive failed scans", DegradationReason.other
                            )

                    await send_pub_sub_message(event)
                    user_id = await self.analytics_event_sender.user_id_from_workspace(event.tenant_id)
                    if first_workspace_collect:
                        await self.analytics_event_sender.send(
                            AEFirstWorkspaceCollectFinished(uuid_str(), context.sent_at, user_id, event.tenant_id)
                        )
                        # inform workspace users about the first successful collect
                        await self.notification_service.send_message_to_workspace(
                            workspace_id=event.tenant_id, message=email.SecurityScanFinished()
                        )
                    if first_account_collect:
                        user_id = await self.analytics_event_sender.user_id_from_workspace(event.tenant_id)
                        await self.analytics_event_sender.send(
                            AEFirstAccountCollectFinished(uuid_str(), context.sent_at, user_id, event.tenant_id)
                        )
                    await self.analytics_event_sender.send(
                        AEWorkspaceCollectFinished(
                            context.id,
                            context.sent_at,
                            user_id,
                            event.tenant_id,
                            len(event.cloud_accounts),
                            sum(a.scanned_resources for a in event.cloud_accounts.values()),
                        )
                    )

                case TenantAccountsCollectFailed.kind:
                    event = TenantAccountsCollected.from_json(message)
                    set_workspace_id(event.tenant_id)
                    for account_id, collect_info in event.cloud_accounts.items():
                        set_fix_cloud_account_id(account_id)
                        set_cloud_account_id(collect_info.account_id)

                        def compute_failed_scan_count(acc: CloudAccount) -> int:
                            if collect_info.scanned_resources < 50:
                                return acc.failed_scan_count + 1
                            else:
                                return 0

                        updated = await self.cloud_account_repository.update(
                            account_id,
                            lambda acc: evolve(
                                acc,
                                last_scan_duration_seconds=collect_info.duration_seconds,
                                last_scan_resources_scanned=collect_info.scanned_resources,
                                last_scan_started_at=collect_info.started_at,
                                next_scan=event.next_run,
                                failed_scan_count=compute_failed_scan_count(acc),
                                last_task_id=collect_info.task_id,
                            ),
                        )

                        if updated.failed_scan_count > 3:
                            await self.__degrade_account(
                                updated.id, "Too many consecutive failed scans", DegradationReason.other
                            )

                case CloudAccountDiscovered.kind:
                    discovered_event = CloudAccountDiscovered.from_json(message)
                    set_cloud_account_id(discovered_event.account_id)
                    set_fix_cloud_account_id(discovered_event.cloud_account_id)
                    set_workspace_id(discovered_event.tenant_id)
                    await self.process_discovered_event(discovered_event)
                    await send_pub_sub_message(discovered_event)

                case CloudAccountConfigured.kind:
                    configured_event = CloudAccountConfigured.from_json(message)
                    await send_pub_sub_message(configured_event)

                case CloudAccountDeleted.kind:
                    deleted_event = CloudAccountDeleted.from_json(message)
                    await send_pub_sub_message(deleted_event)

                case CloudAccountDegraded.kind:
                    degraded_event = CloudAccountDegraded.from_json(message)
                    workspace = await self.workspace_repository.get_workspace(degraded_event.tenant_id)
                    if workspace is None:
                        log.error(f"Workspace {degraded_event.tenant_id} not found, can't send email")
                        return None
                    await self.notification_service.send_message_to_workspace(
                        workspace_id=degraded_event.tenant_id,
                        message=email.AccountDegraded(
                            cloud=degraded_event.cloud,
                            cloud_account_id=degraded_event.account_id,
                            tenant_id=degraded_event.tenant_id,
                            workspace_name=workspace.name,
                            account_name=degraded_event.account_name,
                            cf_stack_deleted=degraded_event.reason == DegradationReason.stack_deleted,
                        ),
                    )
                    await send_pub_sub_message(degraded_event)

                case ProductTierChanged.kind:
                    ptc_evt = ProductTierChanged.from_json(message)
                    # update next tenant run
                    await self.next_run_repository.update_next_run_for(ptc_evt.workspace_id, ptc_evt.product_tier)
                    # check if we need to delete accounts
                    new_account_limit = ProductTierSettings[ptc_evt.product_tier].account_limit or math.inf
                    old_account_limit = ProductTierSettings[ptc_evt.previous_tier].account_limit or math.inf
                    workspace = await self.workspace_repository.get_workspace(ptc_evt.workspace_id)
                    if workspace is None:
                        log.error(f"Workspace {ptc_evt.workspace_id} not found, can't delete cloud accounts")
                        return None
                    user_id = ptc_evt.user_id or workspace.owner_id
                    if new_account_limit < old_account_limit:
                        # we should not have infinity here
                        new_account_limit = round(new_account_limit)
                        # tier changed, time to delete accounts
                        all_accounts = await self.list_accounts(ptc_evt.workspace_id)
                        # keep the last new_account_limit accounts
                        to_delete = all_accounts[:-new_account_limit]
                        # delete them all in parallel
                        async with asyncio.TaskGroup() as tg:
                            for cloud_account in to_delete:
                                tg.create_task(
                                    self.delete_cloud_account(user_id, cloud_account.id, ptc_evt.workspace_id)
                                )

                case SubscriptionCancelled.kind:
                    evt = SubscriptionCancelled.from_json(message)
                    workspaces = await self.workspace_repository.list_workspaces_by_subscription_id(evt.subscription_id)
                    for ws in workspaces:
                        # first move the tier to free
                        await self.workspace_repository.update_payment_on_hold(ws.id, utc())
                        # second remove the subscription from the workspace
                        await self.workspace_repository.update_subscription(ws.id, None)
                        # third disable all accounts
                        account_limit = Free.account_limit or 1
                        await self.disable_cloud_accounts(ws.id, account_limit)

                case SubscriptionCreated.kind:
                    sub_created_evt = SubscriptionCreated.from_json(message)
                    workspaces = await self.workspace_repository.list_workspaces_by_subscription_id(
                        sub_created_evt.subscription_id
                    )
                    for ws in workspaces:
                        # cleanup payment onhold status
                        await self.workspace_repository.update_payment_on_hold(ws.id, None)

                case _:  # pragma: no cover
                    pass  # ignore other domain events

    async def process_discovered_event(self, discovered: CloudAccountDiscovered) -> None:
        account = await self.cloud_account_repository.get(discovered.cloud_account_id)
        if account is None:
            log.warning(f"Account {discovered.cloud_account_id} not found, cannot setup account")
            return None
        await self.configure_account(account, called_from_event=True)

    async def configure_discovered_accounts(self) -> None:
        accounts = await self.cloud_account_repository.list_all_discovered_accounts()
        for account in accounts:
            # If the account is in discovered state for too long - mark it as degraded.
            # The user will see the degraded state in the UI and can eventually fix the problem.
            if (utc() - account.state_updated_at) > timedelta(minutes=30):
                log.info(f"Account {account.id} has been in discovered state for too long, degrading account")
                await self.__degrade_account(
                    account.id, "Account in discovered state for too long", DegradationReason.other
                )
                continue
            try:
                await self.configure_account(account, called_from_event=False)
            except Exception as ex:
                log.warning(f"Failed to configure account {account}: {ex}")

    async def configure_account(
        self,
        account: CloudAccount,
        *,
        called_from_event: bool,
    ) -> CloudAccount | ConfigurationFailure:
        set_cloud_account_id(account.account_id)
        set_fix_cloud_account_id(account.id)
        set_workspace_id(account.workspace_id)

        if account.cloud != "aws":
            log.warning(f"Account {account.id} is not an AWS account, cannot setup account")
            return UnknownCloud(account.cloud)

        log.info("Trying to configure account {account.id}")

        match account.state:
            case CloudAccountStates.Discovered(access):
                match access:
                    case AwsCloudAccess(external_id, role_name):
                        pass
                    case _:  # pragma: no cover
                        log.warning(f"Account {account.id} has unknown access type {access}")
                        return UnknownAccessType(access)
            case _:  # pragma: no cover
                log.warning(f"Account {account.id} is not configurable, cannot setup account")
                return WrongAccountState(account.state)

        if role_name is None:
            log.warning(f"Account {account.id} has no role name, cannot setup account")
            return RoleNameMissing()

        log.info("Trying to assume role")
        assume_role_result = await self.account_setup_helper.can_assume_role(account.account_id, role_name, external_id)

        privileged = False
        match assume_role_result:
            case AssumeRoleResults.Failure(reason):
                trying_to_configure_time = utc() - account.state_updated_at

                def should_move_to_degraded() -> bool:
                    return (not called_from_event) and trying_to_configure_time > self.become_degraded_timeout

                def fast_lane_should_end() -> bool:
                    return called_from_event and trying_to_configure_time > self.fast_lane_timeout

                if should_move_to_degraded():
                    log.info("failed to assume role, but timeout is reached, moving account to degraded state")
                    error = "Cannot assume role"
                    await self.__degrade_account(account.id, error, DegradationReason.other)
                    return CantAssumeRole(retry_limit_reached=True)
                elif fast_lane_should_end():
                    log.info("Can't assume role, leaving account in discovered state")
                    return CantAssumeRole(retry_limit_reached=False)
                else:
                    msg = f"Cannot assume role for account {account.id}: {reason}, retrying again later"
                    log.info(msg)
                    raise RuntimeError(msg)

            case AssumeRoleResults.Success() as assume_role_result:
                log.info("Assume role successful")
                # We are allowed to assume the role.
                # Make sure we also have the permissions to describe regions
                # This additional test makes sure that also the custom permissions are already deployed
                await self.account_setup_helper.allowed_to_describe_regions(assume_role_result)
                log.info("Describe regions successful")
                # If we come here, we did our best to make sure the role with all permissions is deployed
                if organization_accounts := await self.account_setup_helper.list_accounts(assume_role_result):
                    log.info("Account is priviledged and can list accounts")
                    log.info(f"Found accounts {organization_accounts}")
                    privileged = True

                    for acc_id, name in organization_accounts.items():
                        log.info(f"Found account, creating or updating names {acc_id}")
                        await self.create_aws_account(
                            workspace_id=account.workspace_id,
                            account_id=acc_id,
                            role_name=None,
                            external_id=external_id,
                            account_name=name,
                        )
                else:
                    log.info("List accounts is not allowed, account is not priviledged")
                    alias = await self.account_setup_helper.list_account_aliases(assume_role_result)
                    if alias:
                        log.info(f"Updating account alias {alias}")
                        await self.cloud_account_repository.update(
                            account.id, lambda account: evolve(account, account_alias=alias)
                        )

        def update_to_configured(cloud_account: CloudAccount) -> CloudAccount:
            state = cloud_account.state
            if isinstance(state, CloudAccountStates.Discovered):
                return evolve(
                    cloud_account,
                    state=CloudAccountStates.Configured(access, enabled=state.enabled, scan=state.enabled),
                    privileged=privileged,
                    state_updated_at=utc(),
                )
            else:
                raise ValueError(f"Account {account.id} is not in the discovered state, skipping")

        try:
            updated_account = await self.cloud_account_repository.update(account.id, update_to_configured)
            log.info(f"Account {account.id} configured")
            await self.domain_events.publish(
                CloudAccountConfigured(
                    cloud=CloudNames.AWS,
                    cloud_account_id=account.id,
                    tenant_id=account.workspace_id,
                    account_id=account.account_id,
                )
            )
            return updated_account
        except ValueError as e:  # pragma: no cover
            log.info(f"Account {account.id} was changed concurrently, skipping: {e}")
            return ConcurrentUpdate()

    async def _should_be_enabled(self, workspace: Workspace) -> bool:
        should_be_enabled = True

        if limit := ProductTierSettings[workspace.current_product_tier()].account_limit:
            existing_accounts = await self.cloud_account_repository.count_by_workspace_id(
                workspace.id, non_deleted=True
            )
            if existing_accounts >= limit:
                should_be_enabled = False

        if workspace.payment_on_hold_since:
            should_be_enabled = False

        return should_be_enabled

    async def create_aws_account(
        self,
        *,
        workspace_id: WorkspaceId,
        account_id: CloudAccountId,
        role_name: Optional[AwsRoleName],
        external_id: ExternalId,
        account_name: Optional[CloudAccountName],
    ) -> CloudAccount:
        """Create a cloud account."""
        set_workspace_id(workspace_id)
        set_cloud_account_id(account_id)

        log.info("create_aws_account called")

        workspace = await self.workspace_repository.get_workspace(workspace_id)
        if workspace is None:
            raise ResourceNotFound("Organization does not exist")
        if not compare_digest(str(workspace.external_id), str(external_id)):
            raise WrongExternalId("External ids does not match")

        should_be_enabled = await self._should_be_enabled(workspace)

        if existing := await self.cloud_account_repository.get_by_account_id(workspace_id, account_id):
            log.info(f"Account already exists in state: {existing.state.state_name}")
            new_name = account_name or existing.account_name
            new_created_at = utc() if existing.state == CloudAccountStates.Deleted() else existing.created_at
            if role_name is None or (  # no change in role name / external id?
                (access := existing.aws_access())
                and access.role_name == role_name
                and access.external_id == external_id
            ):
                log.info(f"Updating account name to {new_name}")
                if new_created_at != existing.created_at:
                    log.info(f"Updating created_at from {existing.created_at} to {new_created_at}")

                result = await self.cloud_account_repository.update(
                    existing.id, lambda acc: evolve(acc, account_name=new_name, created_at=new_created_at)
                )
                if existing.final_name() != result.final_name():
                    await self.domain_events.publish(
                        CloudAccountNameChanged(
                            result.id,
                            workspace_id,
                            result.cloud,
                            result.account_id,
                            result.state.state_name,
                            result.user_account_name,
                            result.final_name(),
                        )
                    )
                return result  # Do not trigger any creation events.
            else:
                # we have a role name: transition to discovered state
                log.info(f"Moving account {existing.account_id} to discovered state because of the new role name")
                new_state: CloudAccountState = CloudAccountStates.Discovered(
                    AwsCloudAccess(external_id, role_name), enabled=should_be_enabled
                )
                result = await self.cloud_account_repository.update(
                    existing.id,
                    lambda acc: evolve(
                        acc, state=new_state, account_name=new_name, state_updated_at=utc(), created_at=new_created_at
                    ),
                )

        else:
            if role_name is None:
                log.info("Account state: Detected")
                new_state = CloudAccountStates.Detected()
            else:
                log.info("Account state: Discovered")
                new_state = CloudAccountStates.Discovered(
                    AwsCloudAccess(external_id, role_name), enabled=should_be_enabled
                )

            created_at = utc()

            account = CloudAccount(
                id=FixCloudAccountId(uuid.uuid4()),
                account_id=account_id,
                workspace_id=workspace_id,
                cloud=CloudNames.AWS,
                state=new_state,
                account_alias=None,
                account_name=account_name,
                user_account_name=None,
                privileged=False,
                next_scan=None,
                last_scan_duration_seconds=0,
                last_scan_resources_scanned=0,
                last_scan_started_at=None,
                created_at=created_at,
                updated_at=created_at,
                state_updated_at=created_at,
                cf_stack_version=0,
                failed_scan_count=0,
                last_task_id=None,
            )
            # create new account
            result = await self.cloud_account_repository.create(account)
            log.info(f"Account {account_id} created")

        # if that's a detected state account,
        # we quit early since they're basically dead for us
        if isinstance(result.state, CloudAccountStates.Detected):
            return result

        await self.domain_events.publish(
            CloudAccountDiscovered(
                cloud=CloudNames.AWS, cloud_account_id=result.id, tenant_id=workspace_id, account_id=account_id
            )
        )
        log.info("AwsAccountDiscovered published")
        return result

    async def create_gcp_account(
        self,
        *,
        workspace_id: WorkspaceId,
        account_id: CloudAccountId,
        key_id: GcpServiceAccountKeyId,
        account_name: Optional[CloudAccountName],
    ) -> CloudAccount:
        """Create a GCP cloud account."""
        set_workspace_id(workspace_id)
        set_cloud_account_id(account_id)

        log.info("create_gcp_account called")

        workspace = await self.workspace_repository.get_workspace(workspace_id)
        if workspace is None:
            raise ResourceNotFound("Organization does not exist")

        if existing := await self.cloud_account_repository.get_by_account_id(workspace_id, account_id):
            log.info("GCP account already exists")
            return existing

        should_be_enabled = await self._should_be_enabled(workspace)

        created_at = utc()
        account = CloudAccount(
            id=FixCloudAccountId(uuid.uuid4()),
            account_id=account_id,
            workspace_id=workspace_id,
            cloud=CloudNames.GCP,
            state=CloudAccountStates.Configured(
                access=GcpCloudAccess(key_id), enabled=should_be_enabled, scan=should_be_enabled
            ),
            account_alias=None,
            account_name=account_name,
            user_account_name=None,
            privileged=False,
            next_scan=None,
            last_scan_duration_seconds=0,
            last_scan_resources_scanned=0,
            last_scan_started_at=None,
            created_at=created_at,
            updated_at=created_at,
            state_updated_at=created_at,
            cf_stack_version=0,
            failed_scan_count=0,
            last_task_id=None,
        )

        result = await self.cloud_account_repository.create(account)
        log.info(f"GCP cloud Account {account_id} created")

        await self.domain_events.publish(
            CloudAccountConfigured(
                cloud=CloudNames.GCP,
                cloud_account_id=result.id,
                tenant_id=workspace_id,
                account_id=account_id,
            )
        )

        return result

    async def create_azure_account(
        self,
        *,
        workspace_id: WorkspaceId,
        account_id: CloudAccountId,
        subscription_credentials_id: AzureSubscriptionCredentialsId,
        account_name: Optional[CloudAccountName],
    ) -> CloudAccount:

        set_workspace_id(workspace_id)
        set_cloud_account_id(account_id)

        log.info("create_azure_account called")

        workspace = await self.workspace_repository.get_workspace(workspace_id)
        if workspace is None:
            raise ResourceNotFound("Organization does not exist")

        if existing := await self.cloud_account_repository.get_by_account_id(workspace_id, account_id):
            log.info("Azure account already exists")
            return existing

        should_be_enabled = await self._should_be_enabled(workspace)

        created_at = utc()
        account = CloudAccount(
            id=FixCloudAccountId(uuid.uuid4()),
            account_id=account_id,
            workspace_id=workspace_id,
            cloud=CloudNames.Azure,
            state=CloudAccountStates.Configured(
                access=AzureCloudAccess(subscription_credentials_id), enabled=should_be_enabled, scan=should_be_enabled
            ),
            account_alias=None,
            account_name=account_name,
            user_account_name=None,
            privileged=False,
            next_scan=None,
            last_scan_duration_seconds=0,
            last_scan_resources_scanned=0,
            last_scan_started_at=None,
            created_at=created_at,
            updated_at=created_at,
            state_updated_at=created_at,
            cf_stack_version=0,
            failed_scan_count=0,
            last_task_id=None,
        )

        result = await self.cloud_account_repository.create(account)
        log.info(f"Azure cloud Account {account_id} created")

        await self.domain_events.publish(
            CloudAccountConfigured(
                cloud=CloudNames.Azure,
                cloud_account_id=result.id,
                tenant_id=workspace_id,
                account_id=account_id,
            )
        )

        return result

    async def delete_cloud_account(
        self, user_id: UserId, cloud_account_id: FixCloudAccountId, workspace_id: WorkspaceId
    ) -> None:
        account = await self.cloud_account_repository.get(cloud_account_id)
        if account is None:
            return None  # account already deleted, do nothing
        if account.workspace_id != workspace_id:
            raise NotAllowed("Deletion of cloud accounts is only allowed by the owning organization.")

        await self.cloud_account_repository.update(
            cloud_account_id,
            lambda acc: evolve(
                acc,
                state_updated_at=utc(),
                state=CloudAccountStates.Deleted(),
                next_scan=None,
                last_scan_resources_scanned=0,
                last_scan_duration_seconds=0,
                last_scan_started_at=None,
            ),
        )
        await self.domain_events.publish(
            CloudAccountDeleted(account.cloud, user_id, cloud_account_id, workspace_id, account.account_id)
        )

    async def get_cloud_account(self, cloud_account_id: FixCloudAccountId, workspace_id: WorkspaceId) -> CloudAccount:
        account = await self.cloud_account_repository.get(cloud_account_id)

        if account is None:
            raise ResourceNotFound(f"Cloud account {cloud_account_id} not found")

        if account.workspace_id != workspace_id:
            raise NotAllowed("This account does not belong to this workspace.")

        return account

    async def list_accounts(self, workspace_id: WorkspaceId) -> List[CloudAccount]:
        return await self.cloud_account_repository.list_by_workspace_id(
            workspace_id,
            non_deleted=True,
        )

    async def update_cloud_account_name(
        self,
        workspace_id: WorkspaceId,
        cloud_account_id: FixCloudAccountId,
        name: Optional[UserCloudAccountName],
    ) -> CloudAccount:
        # make sure access is possible
        existing = await self.get_cloud_account(cloud_account_id, workspace_id)
        if existing.user_account_name == name:
            return existing
        else:
            result = await self.cloud_account_repository.update(
                cloud_account_id, lambda acc: evolve(acc, user_account_name=name)
            )
            await self.domain_events.publish(
                CloudAccountNameChanged(
                    cloud_account_id,
                    workspace_id,
                    result.cloud,
                    result.account_id,
                    result.state.state_name,
                    name,
                    result.final_name(),
                )
            )
            return result

    async def update_cloud_account_enabled(
        self, workspace_id: WorkspaceId, cloud_account_id: FixCloudAccountId, enabled: bool
    ) -> CloudAccount:
        # make sure access is possible
        await self.get_cloud_account(cloud_account_id, workspace_id)
        workspace = await self.workspace_repository.get_workspace(workspace_id)
        if workspace is None:
            raise ResourceNotFound()
        accounts_count = await self.cloud_account_repository.count_by_workspace_id(
            workspace_id=workspace_id, ready_for_collection=True
        )

        def update_state(cloud_account: CloudAccount, workspace: Workspace) -> CloudAccount:
            match cloud_account.state:
                case CloudAccountStates.Configured(access, _, scan):
                    if enabled:
                        if limit := ProductTierSettings[workspace.current_product_tier()].account_limit:
                            if accounts_count >= limit:
                                raise NotAllowed("Account limit reached")
                        if workspace.payment_on_hold_since:
                            raise NotAllowed("Payment on hold")
                    return evolve(cloud_account, state=CloudAccountStates.Configured(access, enabled, scan))
                case _:  # pragma: no cover
                    raise WrongState(f"Account {cloud_account_id} is not configured, cannot enable account")

        result = await self.cloud_account_repository.update(
            cloud_account_id, partial(update_state, workspace=workspace)
        )
        await self.domain_events.publish(
            CloudAccountActiveToggled(
                tenant_id=workspace_id, cloud_account_id=cloud_account_id, account_id=result.account_id, enabled=enabled
            )
        )
        return result

    async def update_cloud_account_scan_enabled(
        self, workspace_id: WorkspaceId, cloud_account_id: FixCloudAccountId, scan: bool
    ) -> CloudAccount:
        # make sure access is possible
        await self.get_cloud_account(cloud_account_id, workspace_id)
        event: Optional[CloudAccountScanToggled] = None

        def update_state(cloud_account: CloudAccount) -> CloudAccount:
            nonlocal event
            match cloud_account.state:
                case CloudAccountStates.Configured(access, enabled, _):
                    event = CloudAccountScanToggled(
                        tenant_id=workspace_id,
                        cloud_account_id=cloud_account.id,
                        account_id=cloud_account.account_id,
                        enabled=enabled,
                        scan=scan,
                    )
                    return evolve(cloud_account, state=CloudAccountStates.Configured(access, enabled, scan))
                case _:  # pragma: no cover
                    raise WrongState(f"Account {cloud_account_id} is not configured, cannot enable account")

        result = await self.cloud_account_repository.update(cloud_account_id, update_state)
        if event:
            await self.domain_events.publish(event)
        return result

    async def disable_cloud_account(
        self,
        workspace_id: WorkspaceId,
        cloud_account_id: FixCloudAccountId,
    ) -> CloudAccount:
        # make sure access is possible
        await self.get_cloud_account(cloud_account_id, workspace_id)

        def update_state(cloud_account: CloudAccount) -> CloudAccount:
            match cloud_account.state:
                case CloudAccountStates.Configured(access, _):
                    return evolve(cloud_account, state=CloudAccountStates.Configured(access, False, False))
                case _:  # pragma: no cover
                    raise WrongState(f"Account {cloud_account_id} is not configured, cannot enable account")

        return await self.cloud_account_repository.update(cloud_account_id, update_state)

    async def __degrade_account(
        self, account_id: FixCloudAccountId, error: str, reason: DegradationReason
    ) -> CloudAccount:
        def set_degraded(cloud_account: CloudAccount) -> CloudAccount:
            if access := cloud_account.state.cloud_access():
                return evolve(
                    cloud_account,
                    next_scan=None,
                    state=CloudAccountStates.Degraded(access, error),
                    state_updated_at=utc(),
                )
            else:
                return cloud_account

        account = await self.cloud_account_repository.update(account_id, set_degraded)
        await self.domain_events.publish(
            CloudAccountDegraded(
                cloud=account.cloud,
                cloud_account_id=account.id,
                tenant_id=account.workspace_id,
                account_id=account.account_id,
                account_name=account.final_name(),
                error=error,
                reason=reason,
            )
        )
        return account

    async def disable_cloud_accounts(self, workspace_id: WorkspaceId, keep_enabled: int) -> None:

        async def disable_account(cloud_account: CloudAccount) -> None:
            try:
                await self.update_cloud_account_enabled(workspace_id, cloud_account.id, False)
            except Exception as e:
                log.warning(f"Failed to disable account {cloud_account.id}: {e}, skipping")

        async with asyncio.TaskGroup() as tg:
            all_accounts = await self.list_accounts(workspace_id)
            # keep the last account_limit accounts
            to_disable = all_accounts[:-keep_enabled]
            for cloud_account in to_disable:
                tg.create_task(disable_account(cloud_account))
