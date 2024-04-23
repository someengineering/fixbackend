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
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
import logging
from dataclasses import replace
from datetime import timedelta
from ssl import Purpose, create_default_context
from typing import Any, Dict

import boto3
from arq import create_pool
from arq.connections import RedisSettings
from fixcloudutils.redis.event_stream import RedisStreamPublisher
from fixcloudutils.redis.pub_sub import RedisPubSubPublisher
from httpx import AsyncClient, Limits, Timeout
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fixbackend.analytics.domain_event_to_analytics import analytics
from fixbackend.auth.user_repository import UserRepository
from fixbackend.billing.billing_job import BillingJob
from fixbackend.billing.service import BillingEntryService
from fixbackend.certificates.cert_store import CertificateStore
from fixbackend.cloud_accounts.account_setup import AwsAccountSetupHelper
from fixbackend.cloud_accounts.repository import CloudAccountRepositoryImpl
from fixbackend.cloud_accounts.service_impl import CloudAccountServiceImpl
from fixbackend.collect.collect_queue import RedisCollectQueue
from fixbackend.config import Config
from fixbackend.dependencies import FixDependencies
from fixbackend.dependencies import ServiceNames as SN  # noqa
from fixbackend.dispatcher.dispatcher_service import DispatcherService
from fixbackend.dispatcher.next_run_repository import NextRunRepository
from fixbackend.domain_events import DomainEventsStreamName
from fixbackend.domain_events.consumers import EmailOnSignupConsumer, ScheduleTrialEndReminder
from fixbackend.domain_events.publisher_impl import DomainEventPublisherImpl
from fixbackend.domain_events.subscriber import DomainEventSubscriber
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.inventory.inventory_client import InventoryClient
from fixbackend.inventory.inventory_service import InventoryService
from fixbackend.jwt import JwtServiceImpl
from fixbackend.metering.metering_repository import MeteringRepository
from fixbackend.notification.email.one_time_email import OneTimeEmailService
from fixbackend.notification.email.scheduled_email import ScheduledEmailSender
from fixbackend.notification.notification_service import NotificationService
from fixbackend.notification.user_notification_repo import UserNotificationSettingsRepositoryImpl
from fixbackend.permissions.role_repository import RoleRepositoryImpl
from fixbackend.sqlalechemy_extensions import EngineMetrics
from fixbackend.subscription.aws_marketplace import AwsMarketplaceHandler
from fixbackend.subscription.stripe_subscription import create_stripe_service
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.workspaces.invitation_repository import InvitationRepositoryImpl
from fixbackend.workspaces.repository import WorkspaceRepositoryImpl

log = logging.getLogger(__name__)


def create_redis(url: str, cfg: Config) -> Redis:
    ca_cert_path = str(cfg.ca_cert) if cfg.ca_cert else None
    kwargs: Dict[str, Any] = dict(ssl_ca_certs=ca_cert_path) if url.startswith("rediss://") else {}
    kwargs["health_check_interval"] = 30
    kwargs["socket_timeout"] = 10
    kwargs["socket_connect_timeout"] = 10
    kwargs["socket_keepalive"] = True
    if cfg.args.redis_password:
        kwargs["password"] = cfg.args.redis_password
    return Redis.from_url(url, decode_responses=True, **kwargs)  # type: ignore


async def base_dependencies(cfg: Config) -> FixDependencies:
    deps = FixDependencies()
    deps.add(SN.config, cfg)
    ca_cert_path = str(cfg.ca_cert) if cfg.ca_cert else None
    client_context = create_default_context(purpose=Purpose.SERVER_AUTH)
    if ca_cert_path:
        client_context.load_verify_locations(ca_cert_path)
    deps.add(
        SN.http_client,
        AsyncClient(
            verify=client_context or True,
            timeout=Timeout(pool=10, connect=10, read=60, write=60),
            follow_redirects=True,
            limits=Limits(max_connections=512, max_keepalive_connections=50),
        ),
    )
    engine = deps.add(
        SN.async_engine,
        create_async_engine(cfg.database_url, pool_size=10, pool_recycle=3600, pool_pre_ping=True),
    )
    EngineMetrics.register(engine)
    deps.add(SN.session_maker, async_sessionmaker(engine))
    deps.add(SN.boto_session, boto3.Session(cfg.aws_access_key_id, cfg.aws_secret_access_key, region_name="us-east-1"))
    return deps


async def application_dependencies(cfg: Config) -> FixDependencies:
    deps = await base_dependencies(cfg)
    ca_cert_path = str(cfg.ca_cert) if cfg.ca_cert else None
    session_maker = deps.session_maker
    http_client = deps.http_client
    arq_redis = deps.add(
        SN.arq_redis,
        await create_pool(
            replace(
                RedisSettings.from_dsn(cfg.redis_queue_url),
                ssl_ca_certs=ca_cert_path,
                password=cfg.args.redis_password,
            )
        ),
    )
    deps.add(SN.readonly_redis, create_redis(cfg.redis_readonly_url, cfg))
    readwrite_redis = deps.add(SN.readwrite_redis, create_redis(cfg.redis_readwrite_url, cfg))
    temp_store_redis = deps.add(SN.temp_store_redis, create_redis(cfg.redis_temp_store_url, cfg))
    domain_event_subscriber = deps.add(
        SN.domain_event_subscriber,
        DomainEventSubscriber(readwrite_redis, cfg, "fixbackend"),
    )
    cloud_account_repo = deps.add(SN.cloud_account_repo, CloudAccountRepositoryImpl(session_maker))
    deps.add(SN.next_run_repo, NextRunRepository(session_maker))
    metering_repo = deps.add(SN.metering_repo, MeteringRepository(session_maker))
    deps.add(SN.collect_queue, RedisCollectQueue(arq_redis))
    graph_db_access = deps.add(SN.graph_db_access, GraphDatabaseAccessManager(cfg, session_maker))
    inventory_client = deps.add(SN.inventory_client, InventoryClient(cfg.inventory_url, http_client))
    inventory_service = deps.add(
        SN.inventory,
        InventoryService(
            inventory_client, graph_db_access, cloud_account_repo, domain_event_subscriber, temp_store_redis
        ),
    )
    fixbackend_events = deps.add(
        SN.domain_event_redis_stream_publisher,
        RedisStreamPublisher(
            readwrite_redis,
            DomainEventsStreamName,
            "fixbackend",
            keep_unprocessed_messages_for=timedelta(days=7),
        ),
    )
    domain_event_publisher = deps.add(SN.domain_event_sender, DomainEventPublisherImpl(fixbackend_events))
    subscription_repo = deps.add(SN.subscription_repo, SubscriptionRepository(session_maker))
    user_repo = deps.add(SN.user_repo, UserRepository(session_maker))
    role_repo = deps.add(SN.role_repository, RoleRepositoryImpl(session_maker))

    workspace_repo = deps.add(
        SN.workspace_repo,
        WorkspaceRepositoryImpl(
            session_maker,
            graph_db_access,
            domain_event_publisher,
            RedisPubSubPublisher(
                redis=readwrite_redis,
                channel="workspaces",
                publisher_name="workspace_service",
            ),
            subscription_repo,
            role_repo,
        ),
    )
    billing_entry_service = deps.add(
        SN.billing_entry_service,
        BillingEntryService(
            subscription_repo, workspace_repo, metering_repo, domain_event_publisher, cfg.billing_period
        ),
    )
    analytics_event_sender = deps.add(
        SN.analytics_event_sender, analytics(cfg, http_client, domain_event_subscriber, workspace_repo)
    )
    deps.add(
        SN.invitation_repository,
        InvitationRepositoryImpl(session_maker, workspace_repo, user_repository=user_repo),
    )
    deps.add(
        SN.aws_marketplace_handler,
        AwsMarketplaceHandler(
            subscription_repo,
            workspace_repo,
            deps.boto_session,
            domain_event_publisher,
            billing_entry_service,
            cfg.args.aws_marketplace_metering_sqs_url,
        ),
    )
    deps.add(
        SN.stripe_service,
        create_stripe_service(cfg, user_repo, subscription_repo, workspace_repo, session_maker, domain_event_publisher),
    )
    cloud_accounts_redis_publisher = RedisPubSubPublisher(
        redis=readwrite_redis,
        channel="cloud_accounts",
        publisher_name="cloud_account_service",
    )

    cert_store = deps.add(SN.certificate_store, CertificateStore(cfg))

    jwt_service = deps.add(SN.jwt_service, JwtServiceImpl(cert_store))

    notification_service = deps.add(
        SN.notification_service,
        NotificationService(
            cfg,
            workspace_repo,
            graph_db_access,
            user_repo,
            inventory_service,
            readwrite_redis,
            session_maker,
            http_client,
            domain_event_publisher,
            domain_event_subscriber,
            jwt_service,
        ),
    )
    one_time_email = deps.add(
        SN.one_time_email_service,
        OneTimeEmailService(notification_service, user_repo, session_maker, dispatching=False),
    )
    deps.add(SN.email_on_signup_consumer, EmailOnSignupConsumer(notification_service, domain_event_subscriber))
    deps.add(SN.schedule_trial_end_reminder_consumer, ScheduleTrialEndReminder(domain_event_subscriber, one_time_email))
    deps.add(
        SN.cloud_account_service,
        CloudAccountServiceImpl(
            workspace_repository=workspace_repo,
            cloud_account_repository=CloudAccountRepositoryImpl(session_maker),
            pubsub_publisher=cloud_accounts_redis_publisher,
            domain_event_publisher=domain_event_publisher,
            readwrite_redis=readwrite_redis,
            config=cfg,
            account_setup_helper=AwsAccountSetupHelper(deps.boto_session),
            dispatching=False,
            http_client=http_client,
            boto_session=deps.boto_session,
            cf_stack_queue_url=cfg.aws_cf_stack_notification_sqs_url,
            notification_service=notification_service,
            analytics_event_sender=analytics_event_sender,
        ),
    )
    deps.add(SN.user_notification_settings_repository, UserNotificationSettingsRepositoryImpl(session_maker))
    return deps


async def dispatcher_dependencies(cfg: Config) -> FixDependencies:
    deps = await base_dependencies(cfg)
    ca_cert_path = str(cfg.ca_cert) if cfg.ca_cert else None
    session_maker = deps.session_maker
    http_client = deps.http_client
    boto_session = deps.boto_session
    arq_redis = deps.add(
        SN.arq_redis,
        await create_pool(
            replace(
                RedisSettings.from_dsn(cfg.redis_queue_url),
                ssl_ca_certs=ca_cert_path,
                password=cfg.args.redis_password,
            )
        ),
    )
    readwrite_redis = deps.add(SN.readwrite_redis, create_redis(cfg.redis_readwrite_url, cfg))
    domain_event_subscriber = deps.add(
        SN.domain_event_subscriber,
        DomainEventSubscriber(readwrite_redis, cfg, "dispatching"),
    )
    temp_store_redis = deps.add(SN.temp_store_redis, create_redis(cfg.redis_temp_store_url, cfg))
    cloud_account_repo = deps.add(SN.cloud_account_repo, CloudAccountRepositoryImpl(session_maker))
    next_run_repo = deps.add(SN.next_run_repo, NextRunRepository(session_maker))
    metering_repo = deps.add(SN.metering_repo, MeteringRepository(session_maker))
    collect_queue = deps.add(SN.collect_queue, RedisCollectQueue(arq_redis))
    graph_db_access = deps.add(SN.graph_db_access, GraphDatabaseAccessManager(cfg, session_maker))
    fixbackend_events = deps.add(
        SN.domain_event_redis_stream_publisher,
        RedisStreamPublisher(
            readwrite_redis,
            DomainEventsStreamName,
            "dispatching",
            keep_unprocessed_messages_for=timedelta(days=7),
        ),
    )
    domain_event_publisher = deps.add(SN.domain_event_sender, DomainEventPublisherImpl(fixbackend_events))
    subscription_repo = deps.add(SN.subscription_repo, SubscriptionRepository(session_maker))
    role_repo = deps.add(SN.role_repository, RoleRepositoryImpl(session_maker))

    workspace_repo = deps.add(
        SN.workspace_repo,
        WorkspaceRepositoryImpl(
            session_maker,
            graph_db_access,
            domain_event_publisher,
            RedisPubSubPublisher(
                redis=readwrite_redis,
                channel="workspaces",
                publisher_name="workspace_service",
            ),
            subscription_repo,
            role_repo,
        ),
    )

    # uncomment once aws marketplace suscriptions are available on prd
    # trial_end_service = deps.add(SN.trial_end_service, TrialEndService(workspace_repo))

    cloud_accounts_redis_publisher = RedisPubSubPublisher(
        redis=readwrite_redis,
        channel="cloud_accounts",
        publisher_name="cloud_account_service",
    )
    user_repo = deps.add(SN.user_repo, UserRepository(session_maker))
    inventory_client = deps.add(SN.inventory_client, InventoryClient(cfg.inventory_url, http_client))
    # in dispatching we do not want to handle domain events: leave it to the app
    inventory_service = deps.add(
        SN.inventory,
        InventoryService(inventory_client, graph_db_access, cloud_account_repo, None, temp_store_redis),
    )

    cert_store = deps.add(SN.certificate_store, CertificateStore(cfg))

    jwt_service = deps.add(SN.jwt_service, JwtServiceImpl(cert_store))

    notification_service = deps.add(
        SN.notification_service,
        NotificationService(
            cfg,
            workspace_repo,
            graph_db_access,
            user_repo,
            inventory_service,
            readwrite_redis,
            session_maker,
            http_client,
            domain_event_publisher,
            domain_event_subscriber,
            jwt_service,
            handle_events=False,  # fixbackend will handle events. dispatching should ignore them.
        ),
    )
    deps.add(
        SN.one_time_email_service,
        OneTimeEmailService(notification_service, user_repo, session_maker, dispatching=True),
    )
    analytics_event_sender = deps.add(
        SN.analytics_event_sender, analytics(cfg, http_client, domain_event_subscriber, workspace_repo)
    )
    deps.add(
        SN.cloud_account_service,
        CloudAccountServiceImpl(
            workspace_repository=workspace_repo,
            cloud_account_repository=CloudAccountRepositoryImpl(session_maker),
            pubsub_publisher=cloud_accounts_redis_publisher,
            domain_event_publisher=domain_event_publisher,
            readwrite_redis=readwrite_redis,
            config=cfg,
            account_setup_helper=AwsAccountSetupHelper(boto_session),
            dispatching=True,
            http_client=http_client,
            boto_session=boto_session,
            cf_stack_queue_url=cfg.aws_cf_stack_notification_sqs_url,
            notification_service=notification_service,
            analytics_event_sender=analytics_event_sender,
        ),
    )
    deps.add(
        SN.dispatching,
        DispatcherService(
            readwrite_redis,
            cloud_account_repo,
            next_run_repo,
            metering_repo,
            collect_queue,
            graph_db_access,
            domain_event_publisher,
            temp_store_redis,
            domain_event_subscriber,
            workspace_repo,
        ),
    )
    deps.add(SN.scheduled_email_sender, ScheduledEmailSender(notification_service.email_sender, session_maker))
    return deps


async def billing_dependencies(cfg: Config) -> FixDependencies:
    deps = await base_dependencies(cfg)
    session_maker = deps.session_maker
    graph_db_access = deps.add(SN.graph_db_access, GraphDatabaseAccessManager(cfg, session_maker))
    readwrite_redis = deps.add(SN.readwrite_redis, create_redis(cfg.redis_readwrite_url, cfg))
    fixbackend_events = deps.add(
        SN.domain_event_redis_stream_publisher,
        RedisStreamPublisher(
            readwrite_redis,
            DomainEventsStreamName,
            "fixbackend",
            keep_unprocessed_messages_for=timedelta(days=7),
        ),
    )
    domain_event_publisher = deps.add(SN.domain_event_sender, DomainEventPublisherImpl(fixbackend_events))
    metering_repo = deps.add(SN.metering_repo, MeteringRepository(session_maker))
    subscription_repo = deps.add(SN.subscription_repo, SubscriptionRepository(session_maker))
    role_repo = deps.add(SN.role_repository, RoleRepositoryImpl(session_maker))
    user_repo = deps.add(SN.user_repo, UserRepository(session_maker))
    workspace_repo = deps.add(
        SN.workspace_repo,
        WorkspaceRepositoryImpl(
            session_maker,
            graph_db_access,
            domain_event_publisher,
            RedisPubSubPublisher(
                redis=readwrite_redis,
                channel="workspaces",
                publisher_name="workspace_service",
            ),
            subscription_repo,
            role_repo,
        ),
    )
    billing_entry_service = deps.add(
        SN.billing_entry_service,
        BillingEntryService(
            subscription_repo, workspace_repo, metering_repo, domain_event_publisher, cfg.billing_period
        ),
    )
    aws_marketplace = deps.add(
        SN.aws_marketplace_handler,
        AwsMarketplaceHandler(
            subscription_repo,
            workspace_repo,
            deps.boto_session,
            domain_event_publisher,
            billing_entry_service,
            cfg.args.aws_marketplace_metering_sqs_url,
        ),
    )
    stripe = deps.add(
        SN.stripe_service,
        create_stripe_service(cfg, user_repo, subscription_repo, workspace_repo, session_maker, domain_event_publisher),
    )
    deps.add(
        SN.billing_job,
        BillingJob(aws_marketplace, stripe, subscription_repo, workspace_repo, billing_entry_service, cfg),
    )
    return deps


async def create_dependencies(config: Config) -> FixDependencies:
    match config.args.mode:
        case "dispatcher":
            return await dispatcher_dependencies(config)
        case "billing":
            return await billing_dependencies(config)
        case _:
            return await application_dependencies(config)