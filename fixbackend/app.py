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
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from ssl import Purpose, create_default_context
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    ClassVar,
    Optional,
    Set,
    Tuple,
    cast,
)

import boto3
import httpx
from arq import create_pool
from arq.connections import RedisSettings
from async_lru import alru_cache
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fixcloudutils.logging import setup_logger
from fixcloudutils.redis.event_stream import RedisStreamPublisher
from fixcloudutils.redis.pub_sub import RedisPubSubPublisher
from httpx import AsyncClient, Limits, Timeout
from prometheus_fastapi_instrumentator import Instrumentator
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.exceptions import HTTPException

from fixbackend import config, dependencies
from fixbackend.analytics.domain_event_to_analytics import analytics
from fixbackend.auth.auth_backend import cookie_transport
from fixbackend.auth.depedencies import refreshed_session_scope
from fixbackend.auth.oauth_router import github_client, google_client
from fixbackend.auth.role_repository import RoleRepositoryImpl
from fixbackend.auth.router import auth_router
from fixbackend.auth.users_router import users_router
from fixbackend.billing_information.service import BillingEntryService
from fixbackend.notification.notification_router import notification_router
from fixbackend.auth.user_repository import UserRepository
from fixbackend.certificates.cert_store import CertificateStore
from fixbackend.cloud_accounts.account_setup import AwsAccountSetupHelper
from fixbackend.cloud_accounts.repository import CloudAccountRepositoryImpl
from fixbackend.cloud_accounts.router import (
    cloud_accounts_callback_router,
    cloud_accounts_router,
)
from fixbackend.billing_information.router import billing_info_router
from fixbackend.notification.notification_service import NotificationService
from fixbackend.sqlalechemy_extensions import EngineMetrics
from fixbackend.cloud_accounts.service_impl import CloudAccountServiceImpl
from fixbackend.collect.collect_queue import RedisCollectQueue
from fixbackend.config import Config
from fixbackend.dependencies import FixDependencies
from fixbackend.dependencies import ServiceNames as SN  # noqa
from fixbackend.dispatcher.dispatcher_service import DispatcherService
from fixbackend.dispatcher.next_run_repository import NextRunRepository
from fixbackend.domain_events import DomainEventsStreamName
from fixbackend.domain_events.consumers import CustomerIoEventConsumer, EmailOnSignupConsumer
from fixbackend.domain_events.publisher_impl import DomainEventPublisherImpl
from fixbackend.errors import NotAllowed, ResourceNotFound, ClientError, WrongState
from fixbackend.events.router import websocket_router
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.inventory.inventory_client import InventoryClient, InventoryException
from fixbackend.inventory.inventory_service import InventoryService
from fixbackend.inventory.router import inventory_router
from fixbackend.logging_context import (
    get_logging_context,
    set_fix_cloud_account_id,
    set_workspace_id,
)
from fixbackend.metering.metering_repository import MeteringRepository
from fixbackend.middleware.x_real_ip import RealIpMiddleware
from fixbackend.subscription.aws_marketplace import AwsMarketplaceHandler
from fixbackend.subscription.billing import BillingService
from fixbackend.subscription.router import subscription_router
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.workspaces.invitation_repository import InvitationRepositoryImpl
from fixbackend.workspaces.repository import WorkspaceRepositoryImpl
from fixbackend.workspaces.router import workspaces_router
from fixbackend.domain_events.subscriber import DomainEventSubscriber

log = logging.getLogger(__name__)
API_PREFIX = "/api"


# noinspection PyUnresolvedReferences
def fast_api_app(cfg: Config) -> FastAPI:
    google = google_client(cfg)
    github = github_client(cfg)
    boto_session = boto3.Session(cfg.aws_access_key_id, cfg.aws_secret_access_key, region_name="us-east-1")
    deps = FixDependencies()
    deps.add(SN.config, cfg)
    ca_cert_path = str(cfg.ca_cert) if cfg.ca_cert else None
    client_context = create_default_context(purpose=Purpose.SERVER_AUTH)
    if ca_cert_path:
        client_context.load_verify_locations(ca_cert_path)
    http_client = deps.add(
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
    session_maker = deps.add(SN.session_maker, async_sessionmaker(engine))

    def create_redis(url: str) -> Redis:
        kwargs = dict(ssl_ca_certs=ca_cert_path) if url.startswith("rediss://") else {}
        if cfg.args.redis_password:
            kwargs["password"] = cfg.args.redis_password
        return Redis.from_url(url, decode_responses=True, **kwargs)  # type: ignore

    @asynccontextmanager
    async def setup_teardown_application(_: FastAPI) -> AsyncIterator[None]:
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
        deps.add(SN.readonly_redis, create_redis(cfg.redis_readonly_url))
        readwrite_redis = deps.add(SN.readwrite_redis, create_redis(cfg.redis_readwrite_url))
        temp_store_redis = deps.add(SN.temp_store_redis, create_redis(cfg.redis_temp_store_url))
        domain_event_subscriber = deps.add(
            SN.domain_event_subscriber,
            DomainEventSubscriber(readwrite_redis, cfg, "fixbackend"),
        )
        deps.add(SN.cloud_account_repo, CloudAccountRepositoryImpl(session_maker))
        deps.add(SN.next_run_repo, NextRunRepository(session_maker))
        metering_repo = deps.add(SN.metering_repo, MeteringRepository(session_maker))
        deps.add(SN.collect_queue, RedisCollectQueue(arq_redis))
        graph_db_access = deps.add(SN.graph_db_access, GraphDatabaseAccessManager(cfg, session_maker))
        inventory_client = deps.add(SN.inventory_client, InventoryClient(cfg.inventory_url, http_client))
        inventory_service = deps.add(
            SN.inventory,
            InventoryService(inventory_client, graph_db_access, domain_event_subscriber, temp_store_redis),
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
        deps.add(
            SN.billing_entry_service, BillingEntryService(subscription_repo, workspace_repo, domain_event_publisher)
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
                metering_repo,
                boto_session,
                cfg.args.aws_marketplace_metering_sqs_url,
                domain_event_publisher,
                cfg.billing_period,
            ),
        )
        deps.add(
            SN.customerio_consumer,
            CustomerIoEventConsumer(http_client, cfg, domain_event_subscriber),
        )
        cloud_accounts_redis_publisher = RedisPubSubPublisher(
            redis=readwrite_redis,
            channel="cloud_accounts",
            publisher_name="cloud_account_service",
        )

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
            ),
        )
        deps.add(SN.email_on_signup_consumer, EmailOnSignupConsumer(notification_service, domain_event_subscriber))
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
                dispatching=False,
                http_client=http_client,
                boto_session=boto_session,
                cf_stack_queue_url=cfg.aws_cf_stack_notification_sqs_url,
                notification_service=notification_service,
                analytics_event_sender=analytics_event_sender,
            ),
        )

        deps.add(SN.certificate_store, CertificateStore(cfg))
        if not cfg.static_assets:
            await load_app_from_cdn()
        async with deps:
            log.info("Application services started.")
            yield None
        await arq_redis.close()
        log.info("Application services stopped.")

    @asynccontextmanager
    async def setup_teardown_dispatcher(_: FastAPI) -> AsyncIterator[None]:
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
        readwrite_redis = deps.add(SN.readwrite_redis, create_redis(cfg.redis_readwrite_url))
        domain_event_subscriber = deps.add(
            SN.domain_event_subscriber,
            DomainEventSubscriber(readwrite_redis, cfg, "dispatching"),
        )
        temp_store_redis = deps.add(SN.temp_store_redis, create_redis(cfg.redis_temp_store_url))
        cloud_accounts = deps.add(SN.cloud_account_repo, CloudAccountRepositoryImpl(session_maker))
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
            InventoryService(inventory_client, graph_db_access, None, temp_store_redis),
        )
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
                handle_events=False,  # fixbackend will handle events. dispatching should ignore them.
            ),
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
                cloud_accounts,
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

        async with deps:
            log.info("Application services started.")
            yield None
        await arq_redis.close()
        log.info("Application services stopped.")

    @asynccontextmanager
    async def setup_teardown_billing(_: FastAPI) -> AsyncIterator[None]:
        graph_db_access = deps.add(SN.graph_db_access, GraphDatabaseAccessManager(cfg, session_maker))
        readwrite_redis = deps.add(SN.readwrite_redis, create_redis(cfg.redis_readwrite_url))
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
        aws_marketplace = deps.add(
            SN.aws_marketplace_handler,
            AwsMarketplaceHandler(
                subscription_repo,
                workspace_repo,
                metering_repo,
                boto_session,
                cfg.args.aws_marketplace_metering_sqs_url,
                domain_event_publisher,
                cfg.billing_period,
            ),
        )
        deps.add(SN.billing, BillingService(aws_marketplace, subscription_repo, workspace_repo))

        async with deps:
            log.info("Application services started.")
            yield None
        log.info("Application services stopped.")

    match cfg.args.mode:
        case "dispatcher":
            lifespan = setup_teardown_dispatcher
        case "billing":
            lifespan = setup_teardown_billing
        case _:
            lifespan = setup_teardown_application

    app = FastAPI(
        title="Fix Backend",
        summary="Backend for the FIX project",
        lifespan=lifespan,
        swagger_ui_parameters=dict(docExpansion=False, tagsSorter="alpha", operationsSorter="alpha"),
    )
    app.dependency_overrides[config.config] = lambda: cfg
    app.dependency_overrides[dependencies.fix_dependencies] = lambda: deps

    if cfg.profiling_enabled:
        from pyinstrument import Profiler

        @app.middleware("http")
        async def profile_request(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
            profiling = request.query_params.get("profile", False)
            if profiling:
                profiler = Profiler(interval=cfg.profiling_interval, async_mode="enabled")
                profiler.start()
                await call_next(request)
                profiler.stop()
                return HTMLResponse(profiler.output_html())
            else:
                return await call_next(request)

    app.add_middleware(RealIpMiddleware)  # type: ignore

    workspaces_prefix = f"{API_PREFIX}/workspaces"

    @app.middleware("http")
    async def add_logging_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        if path.startswith(workspaces_prefix):
            parts = iter(path.split("/"))
            for part in parts:
                match part:
                    case "api" | "":
                        continue
                    case "workspaces":
                        if workspace_id := next(parts, None):
                            set_workspace_id(workspace_id)
                    case "cloud_account":
                        if cloud_account_id := next(parts, None):
                            set_fix_cloud_account_id(cloud_account_id)

        response = await call_next(request)

        return response

    @app.exception_handler(NotAllowed)
    async def access_denied_handler(_: Request, exception: NotAllowed) -> Response:
        return JSONResponse(status_code=403, content={"message": str(exception)})

    @app.exception_handler(ResourceNotFound)
    async def resource_not_found_handler(_: Request, exception: ResourceNotFound) -> Response:
        return JSONResponse(status_code=404, content={"message": str(exception)})

    @app.exception_handler(InventoryException)
    async def inventory_exception_handler(_: Request, exception: InventoryException) -> Response:
        return JSONResponse(status_code=exception.status, content={"message": str(exception)})

    @app.exception_handler(WrongState)
    async def wrong_state_handler(_: Request, exception: WrongState) -> Response:
        return JSONResponse(status_code=409, content={"message": str(exception)})

    @app.exception_handler(ClientError)
    async def client_error_handler(_: Request, exception: ClientError) -> Response:
        return JSONResponse(status_code=400, content={"message": str(exception)})

    class EndpointFilter(logging.Filter):
        endpoints_to_filter: ClassVar[Set[str]] = {
            "/health",
            "/ready",
            "/metrics",
        }

        def filter(self, record: logging.LogRecord) -> bool:
            args = cast(Optional[Tuple[Any, ...]], record.args)
            return (args is not None) and len(args) >= 3 and args[2] not in self.endpoints_to_filter

    # Add filter to the logger
    logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

    @alru_cache(maxsize=1)
    async def load_app_from_cdn() -> bytes:
        async with httpx.AsyncClient() as client:
            log.info("Loading app from CDN")
            response = await client.get(f"{cfg.frontend_cdn_origin()}/index.html")
            log.info("Loaded app from CDN")
            body = response.content
            return body

    @app.get("/health", tags=["system"])
    async def health() -> Response:
        return Response(status_code=200)

    @app.get("/ready", tags=["system"])
    async def ready() -> Response:
        return Response(status_code=200)

    @app.get("/api/info", tags=["system"])
    async def info() -> Response:
        return JSONResponse(
            dict(
                environment=cfg.environment,
                aws_marketplace_url=cfg.aws_marketplace_url,
            )
        )

    @app.get("/docs/events", include_in_schema=False)
    async def domain_events_swagger_ui_html(req: Request) -> HTMLResponse:
        root_path = req.scope.get("root_path", "").rstrip("/")
        openapi_url = root_path + "/static/openapi-events.yaml"
        return get_swagger_ui_html(
            openapi_url=openapi_url,
            title="Fix Domain Events - Swagger UI",
            oauth2_redirect_url=None,
            init_oauth=None,
            swagger_ui_parameters=None,
        )

    Instrumentator().instrument(
        app,
        should_only_respect_2xx_for_highr=True,
        latency_lowr_buckets=(0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 1.5, 2),
    ).expose(app, tags=["system"])

    if cfg.args.mode == "app":
        api_router = APIRouter(prefix=API_PREFIX)
        api_router.include_router(auth_router(cfg, google, github), prefix="/auth", tags=["auth"])

        api_router.include_router(workspaces_router(), prefix="/workspaces", tags=["workspaces"])
        api_router.include_router(cloud_accounts_router(), prefix="/workspaces", tags=["cloud_accounts"])
        api_router.include_router(inventory_router(deps), prefix="/workspaces")
        api_router.include_router(websocket_router(cfg), prefix="/workspaces", tags=["events"])
        api_router.include_router(cloud_accounts_callback_router(), prefix="/cloud", tags=["cloud_accounts"])
        api_router.include_router(users_router(), prefix="/users", tags=["users"])
        api_router.include_router(subscription_router(), tags=["billing"])
        api_router.include_router(billing_info_router(), prefix="/workspaces", tags=["billing"])
        api_router.include_router(notification_router(deps), prefix="/workspaces", tags=["notification"])

        app.include_router(api_router)
        app.mount("/static", StaticFiles(directory="static"), name="static")

        cookie = cookie_transport(cfg.session_ttl)

        @app.middleware("http")
        async def refresh_session(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
            response = await call_next(request)
            if refresh_session_token := request.scope.get(refreshed_session_scope):
                # refresh the session token on every request
                cookie._set_login_cookie(response, refresh_session_token)  # noqa

            return response

        if cfg.static_assets:
            app.mount(
                "/",
                StaticFiles(directory=cfg.static_assets, html=True),
                name="static_assets",
            )

        @app.get("/", include_in_schema=False)
        async def root(_: Request) -> Response:
            body = await load_app_from_cdn()
            return Response(content=body, media_type="text/html", headers={"fix-environment": cfg.environment})

        @app.exception_handler(404)
        async def not_found_handler(request: Request, exception: HTTPException) -> Response:
            if request.url.path.startswith(API_PREFIX):
                return await http_exception_handler(request, exception)
            return await root(request)

        # ttl does not matter here since this cookie is only used for logout
        logout_cookie = cookie_transport(1)

        @app.exception_handler(401)
        async def unauthorized_handler(request: Request, exception: HTTPException) -> Response:
            response = await http_exception_handler(request, exception)
            logout_cookie._set_logout_cookie(response)  # noqa
            return response

    return app


def setup_process() -> FastAPI:
    """
    This function is used by uvicorn to start the server.
    Entrypoint for the application to start the server.
    """
    current_config = config.get_config()
    level = logging.DEBUG if current_config.args.debug else logging.INFO
    setup_logger(
        f"fixbackend_{current_config.args.mode}",
        level=level,
        get_logging_context=get_logging_context,
    )

    # Replace all special uvicorn handlers
    for logger in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        lg = logging.getLogger(logger)
        lg.handlers.clear()  # remove handlers
        lg.propagate = True  # propagate to root, so the handlers there are used

    return fast_api_app(current_config)
