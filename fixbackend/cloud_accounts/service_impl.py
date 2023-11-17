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


import uuid
from collections import defaultdict
from datetime import timedelta
from hmac import compare_digest
from logging import getLogger
from typing import Any, Dict, List, Optional

from attrs import evolve
from fixcloudutils.asyncio.periodic import Periodic
from fixcloudutils.redis.event_stream import Backoff, DefaultBackoff, Json, MessageContext, RedisStreamListener
from fixcloudutils.redis.pub_sub import RedisPubSubPublisher
from fixcloudutils.service import Service
from fixcloudutils.util import utc
from redis.asyncio import Redis

from fixbackend.cloud_accounts.account_setup import AssumeRoleResults, AwsAccountSetupHelper
from fixbackend.cloud_accounts.models import AwsCloudAccess, CloudAccount, CloudAccountState, CloudAccountStates
from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.cloud_accounts.service import CloudAccountService, WrongExternalId
from fixbackend.config import Config
from fixbackend.domain_events import DomainEventsStreamName
from fixbackend.domain_events.events import (
    AwsAccountConfigured,
    AwsAccountDeleted,
    AwsAccountDiscovered,
    TenantAccountsCollected,
    AwsAccountDegraded,
)
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.errors import AccessDenied, ResourceNotFound
from fixbackend.ids import (
    AwsRoleName,
    CloudAccountId,
    CloudAccountName,
    CloudNames,
    ExternalId,
    FixCloudAccountId,
    UserCloudAccountName,
    WorkspaceId,
)
from fixbackend.logging_context import set_cloud_account_id, set_fix_cloud_account_id, set_workspace_id
from fixbackend.workspaces.repository import WorkspaceRepository

log = getLogger(__name__)


class CloudAccountServiceImpl(CloudAccountService, Service):
    def __init__(
        self,
        workspace_repository: WorkspaceRepository,
        cloud_account_repository: CloudAccountRepository,
        pubsub_publisher: RedisPubSubPublisher,
        domain_event_publisher: DomainEventPublisher,
        readwrite_redis: Redis,
        config: Config,
        account_setup_helper: AwsAccountSetupHelper,
        dispatching: bool,
    ) -> None:
        self.workspace_repository = workspace_repository
        self.cloud_account_repository = cloud_account_repository
        self.pubsub_publisher = pubsub_publisher
        self.domain_events = domain_event_publisher

        backoff_config: Dict[str, Backoff] = defaultdict(lambda: DefaultBackoff)
        backoff_config[AwsAccountDiscovered.kind] = Backoff(
            base_delay=5,
            maximum_delay=10,
            retries=8,
            log_failed_attempts=False,
        )
        if dispatching:
            self.periodic = Periodic(
                "conifugure_discovered_accounts", self.configure_discovered_accounts, timedelta(minutes=1)
            )

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
        self.instance_id = config.instance_id
        self.account_setup_helper = account_setup_helper
        self.dispatching = dispatching
        self.fast_lane_timeout = timedelta(minutes=1)
        self.become_degraded_timeout = timedelta(minutes=15)

    async def start(self) -> Any:
        await self.domain_event_listener.start()
        await self.periodic.start()

    async def stop(self) -> Any:
        await self.domain_event_listener.stop()
        await self.periodic.stop()

    async def process_domain_event(self, message: Json, context: MessageContext) -> None:
        match context.kind:
            case TenantAccountsCollected.kind:
                event = TenantAccountsCollected.from_json(message)
                set_workspace_id(str(event.tenant_id))
                for account_id, account in event.cloud_accounts.items():
                    set_fix_cloud_account_id(account_id)
                    set_cloud_account_id(account.account_id)
                    await self.cloud_account_repository.update(
                        account_id,
                        lambda acc: evolve(
                            acc,
                            last_scan_duration_seconds=account.duration_seconds,
                            last_scan_resources_scanned=account.scanned_resources,
                            last_scan_started_at=account.started_at,
                            next_scan=event.next_run,
                        ),
                    )

            case AwsAccountDiscovered.kind:
                discovered_event = AwsAccountDiscovered.from_json(message)
                set_cloud_account_id(discovered_event.aws_account_id)
                set_fix_cloud_account_id(str(discovered_event.cloud_account_id))
                set_workspace_id(str(discovered_event.tenant_id))
                await self.process_discovered_event(discovered_event)

            case _:
                pass  # ignore other domain events

    async def process_discovered_event(self, discovered: AwsAccountDiscovered) -> None:
        account = await self.cloud_account_repository.get(discovered.cloud_account_id)
        if account is None:
            log.warning(f"Account {discovered.cloud_account_id} not found, cannot setup account")
            return None
        await self.configure_account(account, called_from_event=True)

    async def configure_discovered_accounts(self) -> None:
        accounts = await self.cloud_account_repository.list_all_discovered_accounts()
        for account in accounts:
            await self.configure_account(account, called_from_event=False)

    async def configure_account(
        self,
        account: CloudAccount,
        *,
        called_from_event: bool,
    ) -> None:
        set_cloud_account_id(account.account_id)
        set_fix_cloud_account_id(str(account.id))
        set_workspace_id(account.workspace_id)

        if account.cloud != "aws":
            log.warning(f"Account {account.id} is not an AWS account, cannot setup account")
            return None

        match account.state:
            case CloudAccountStates.Discovered(access):
                match access:
                    case AwsCloudAccess(external_id, role_name):
                        pass
                    case _:
                        log.warning(f"Account {account.id} has unknown access type {access}")
                        return None
            case _:
                log.warning(f"Account {account.id} is not configurable, cannot setup account")
                return None

        if role_name is None:
            log.warning(f"Account {account.id} has no role name, cannot setup account")
            return None

        log.info(f"Waiting for account {account.id} to be configured")

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

                    def update_fn(cloud_account: CloudAccount) -> CloudAccount:
                        if isinstance(cloud_account.state, CloudAccountStates.Discovered):
                            return evolve(
                                cloud_account, state=CloudAccountStates.Degraded(access, error), state_updated_at=utc()
                            )
                        else:
                            return cloud_account

                    await self.cloud_account_repository.update(account.id, update_fn)
                    await self.domain_events.publish(
                        AwsAccountDegraded(
                            cloud_account_id=account.id,
                            tenant_id=account.workspace_id,
                            aws_account_id=account.account_id,
                            error=error,
                        )
                    )
                    return None
                elif fast_lane_should_end():
                    log.info("Can't assume role, leaving account in discovered state")
                    return None
                else:
                    msg = f"Cannot assume role for account {account.id}: {reason}, retrying again later"
                    log.info(msg)
                    raise RuntimeError(msg)

            case AssumeRoleResults.Success() as assume_role_result:
                if organization_accounts := await self.account_setup_helper.list_accounts(assume_role_result):
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
                    alias = await self.account_setup_helper.list_account_aliases(assume_role_result)
                    log.info(f"Calling list_accounts is not allowed, using alias {alias} as an alternative")
                    if alias:
                        await self.cloud_account_repository.update(
                            account.id, lambda account: evolve(account, account_alias=alias)
                        )

        def update_to_configured(cloud_account: CloudAccount) -> CloudAccount:
            if isinstance(cloud_account.state, CloudAccountStates.Discovered):
                return evolve(
                    cloud_account,
                    state=CloudAccountStates.Configured(access, True),
                    privileged=privileged,
                    state_updated_at=utc(),
                )
            else:
                raise ValueError(f"Account {account.id} is not in the discovered state, skipping")

        try:
            await self.cloud_account_repository.update(account.id, update_to_configured)
            log.info(f"Account {account.id} configured")
            await self.domain_events.publish(
                AwsAccountConfigured(
                    cloud_account_id=account.id,
                    tenant_id=account.workspace_id,
                    aws_account_id=account.account_id,
                )
            )
        except ValueError as e:
            log.info(f"Account {account.id} was changed concurrently, skipping: {e}")

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

        organization = await self.workspace_repository.get_workspace(workspace_id)
        if organization is None:
            raise ValueError("Organization does not exist")
        if not compare_digest(str(organization.external_id), str(external_id)):
            raise WrongExternalId("External ids does not match")

        async def account_already_exists(workspace_id: WorkspaceId, account_id: str) -> Optional[CloudAccount]:
            accounts = await self.cloud_account_repository.list_by_workspace_id(workspace_id)
            maybe_account = next(
                iter([account for account in accounts if account.account_id == account_id]),
                None,
            )
            return maybe_account

        # if existing, only update name and aliases, no need for events
        if existing := await account_already_exists(workspace_id, account_id):
            new_name = account_name or existing.account_name
            match existing.state:
                # detected and degraded can transition to Discovered or stay where they are
                case CloudAccountStates.Detected() | CloudAccountStates.Degraded() | CloudAccountStates.Discovered():
                    match role_name:
                        case None:
                            # no new role name provided, update the account name if possible
                            # and stay in the same state. Return to not trigger any events
                            result = await self.cloud_account_repository.update(
                                existing.id,
                                lambda acc: evolve(acc, account_name=account_name or new_name),
                            )
                            return result
                        case role_name:
                            # we have a role name, hence we transition to discovered
                            new_state: CloudAccountState = CloudAccountStates.Discovered(
                                AwsCloudAccess(external_id, role_name)
                            )
                            result = await self.cloud_account_repository.update(
                                existing.id,
                                lambda acc: evolve(
                                    acc, state=new_state, account_name=account_name or new_name, state_updated_at=utc()
                                ),
                            )

                # in case of configured, update the name and return immediately
                case _:
                    result = await self.cloud_account_repository.update(
                        existing.id, lambda acc: evolve(acc, account_name=account_name)
                    )
                    return result
        else:
            if role_name is None:
                new_state = CloudAccountStates.Detected()
            else:
                new_state = CloudAccountStates.Discovered(AwsCloudAccess(external_id, role_name))

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
            )
            # create new account
            result = await self.cloud_account_repository.create(account)

        # if that's a detected state account,
        # we quit early since they're basically dead for us
        if isinstance(result.state, CloudAccountStates.Detected):
            return result

        message = {
            "cloud_account_id": str(result.id),
            "workspace_id": str(result.workspace_id),
            "aws_account_id": account_id,
        }
        await self.pubsub_publisher.publish(
            kind="cloud_account_created", message=message, channel=f"tenant-events::{workspace_id}"
        )
        await self.domain_events.publish(
            AwsAccountDiscovered(cloud_account_id=result.id, tenant_id=workspace_id, aws_account_id=account_id)
        )
        return result

    async def delete_cloud_account(self, cloud_account_id: FixCloudAccountId, workspace_id: WorkspaceId) -> None:
        account = await self.cloud_account_repository.get(cloud_account_id)
        if account is None:
            return None  # account already deleted, do nothing
        if account.workspace_id != workspace_id:
            raise AccessDenied("Deletion of cloud accounts is only allowed by the owning organization.")

        await self.cloud_account_repository.delete(cloud_account_id)
        await self.domain_events.publish(AwsAccountDeleted(cloud_account_id, workspace_id, account.account_id))

    async def get_cloud_account(self, cloud_account_id: FixCloudAccountId, workspace_id: WorkspaceId) -> CloudAccount:
        account = await self.cloud_account_repository.get(cloud_account_id)

        if account is None:
            raise ResourceNotFound(f"Cloud account {cloud_account_id} not found")

        if account.workspace_id != workspace_id:
            raise AccessDenied("This account does not belong to this workspace.")

        return account

    async def list_accounts(self, workspace_id: WorkspaceId) -> List[CloudAccount]:
        return await self.cloud_account_repository.list_by_workspace_id(workspace_id)

    async def update_cloud_account_name(
        self,
        workspace_id: WorkspaceId,
        cloud_account_id: FixCloudAccountId,
        name: Optional[UserCloudAccountName],
    ) -> CloudAccount:
        # make sure access is possible
        await self.get_cloud_account(cloud_account_id, workspace_id)
        return await self.cloud_account_repository.update(
            cloud_account_id, lambda acc: evolve(acc, user_account_name=name)
        )

    async def enable_cloud_account(
        self,
        workspace_id: WorkspaceId,
        cloud_account_id: FixCloudAccountId,
    ) -> CloudAccount:
        # make sure access is possible
        await self.get_cloud_account(cloud_account_id, workspace_id)

        def update_state(cloud_account: CloudAccount) -> CloudAccount:
            match cloud_account.state:
                case CloudAccountStates.Configured(access, _):
                    return evolve(cloud_account, state=CloudAccountStates.Configured(access, True))
                case _:
                    raise ValueError(f"Account {cloud_account_id} is not configured, cannot enable account")

        result = await self.cloud_account_repository.update(cloud_account_id, update_state)
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
                    return evolve(cloud_account, state=CloudAccountStates.Configured(access, False))
                case _:
                    raise ValueError(f"Account {cloud_account_id} is not configured, cannot enable account")

        return await self.cloud_account_repository.update(cloud_account_id, update_state)
