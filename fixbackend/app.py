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
from typing import Any, AsyncIterator, Awaitable, Callable, ClassVar, Optional, Set, Tuple, cast

import boto3
import httpx
from arq import create_pool
from arq.connections import RedisSettings
from async_lru import alru_cache
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fixcloudutils.logging import setup_logger
from fixcloudutils.redis.event_stream import RedisStreamPublisher
from fixcloudutils.redis.pub_sub import RedisPubSubPublisher
from httpx import AsyncClient
from prometheus_fastapi_instrumentator import Instrumentator
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.exceptions import HTTPException

from fixbackend import config, dependencies
from fixbackend.auth.auth_backend import cookie_transport
from fixbackend.auth.depedencies import refreshed_session_scope
from fixbackend.auth.oauth import github_client, google_client
from fixbackend.auth.router import auth_router, users_router
from fixbackend.certificates.cert_store import CertificateStore
from fixbackend.cloud_accounts.account_setup import AwsAccountSetupHelper
from fixbackend.cloud_accounts.last_scan_repository import LastScanRepository
from fixbackend.cloud_accounts.repository import CloudAccountRepositoryImpl
from fixbackend.cloud_accounts.router import cloud_accounts_callback_router, cloud_accounts_router
from fixbackend.cloud_accounts.service_impl import CloudAccountServiceImpl
from fixbackend.collect.collect_queue import RedisCollectQueue
from fixbackend.config import Config
from fixbackend.dependencies import FixDependencies
from fixbackend.dependencies import ServiceNames as SN
from fixbackend.dispatcher.dispatcher_service import DispatcherService
from fixbackend.dispatcher.next_run_repository import NextRunRepository
from fixbackend.domain_events import DomainEventsStreamName
from fixbackend.domain_events.consumers import CustomerIoEventConsumer
from fixbackend.domain_events.publisher_impl import DomainEventPublisherImpl
from fixbackend.errors import AccessDenied, ResourceNotFound
from fixbackend.events.router import websocket_router
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.inventory.inventory_client import InventoryClient
from fixbackend.inventory.inventory_service import InventoryService
from fixbackend.inventory.router import inventory_router
from fixbackend.metering.metering_repository import MeteringRepository
from fixbackend.middleware.x_real_ip import RealIpMiddleware
from fixbackend.subscription.aws_marketplace import AwsMarketplaceHandler
from fixbackend.subscription.billing import BillingService
from fixbackend.subscription.router import subscription_router
from fixbackend.subscription.subscription_repository import SubscriptionRepository
from fixbackend.workspaces.repository import WorkspaceRepositoryImpl
from fixbackend.workspaces.router import workspaces_router

log = logging.getLogger(__name__)
API_PREFIX = "/api"


# noinspection PyUnresolvedReferences
def fast_api_app(cfg: Config) -> FastAPI:
    google = google_client(cfg)
    github = github_client(cfg)
    boto_session = boto3.Session(cfg.aws_access_key_id, cfg.aws_secret_access_key, region_name="us-east-1")
    deps = FixDependencies()
    ca_cert_path = str(cfg.ca_cert) if cfg.ca_cert else None
    client_context = create_default_context(purpose=Purpose.SERVER_AUTH)
    if ca_cert_path:
        client_context.load_verify_locations(ca_cert_path)

    def create_redis(url: str) -> Redis:
        kwargs = dict(ssl_ca_certs=ca_cert_path) if url.startswith("rediss://") else {}
        if cfg.args.redis_password:
            kwargs["password"] = cfg.args.redis_password
        return Redis.from_url(url, decode_responses=True, **kwargs)  # type: ignore

    @asynccontextmanager
    async def setup_teardown_application(_: FastAPI) -> AsyncIterator[None]:
        http_client = deps.add(SN.http_client, AsyncClient(verify=ca_cert_path or True))
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
        engine = deps.add(
            SN.async_engine,
            create_async_engine(
                cfg.database_url,
                pool_size=10,
                pool_recycle=3600,
                pool_pre_ping=True,
                # connect_args=dict(ssl=client_context)
            ),
        )
        session_maker = deps.add(SN.session_maker, async_sessionmaker(engine))
        deps.add(SN.cloud_account_repo, CloudAccountRepositoryImpl(session_maker))
        deps.add(SN.next_run_repo, NextRunRepository(session_maker))
        metering_repo = deps.add(SN.metering_repo, MeteringRepository(session_maker))
        deps.add(SN.collect_queue, RedisCollectQueue(arq_redis))
        graph_db_access = deps.add(SN.graph_db_access, GraphDatabaseAccessManager(cfg, session_maker))
        inventory_client = deps.add(SN.inventory_client, InventoryClient(cfg.inventory_url, http_client))
        deps.add(SN.inventory, InventoryService(inventory_client))
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
        workspace_repo = deps.add(
            SN.workspace_repo, WorkspaceRepositoryImpl(session_maker, graph_db_access, domain_event_publisher)
        )
        subscription_repo = deps.add(SN.subscription_repo, SubscriptionRepository(session_maker))
        deps.add(
            SN.aws_marketplace_handler,
            AwsMarketplaceHandler(
                subscription_repo,
                workspace_repo,
                metering_repo,
                boto_session,
                cfg.args.aws_marketplace_metering_sqs_url,
            ),
        )
        deps.add(
            SN.customerio_consumer,
            CustomerIoEventConsumer(http_client, cfg, readwrite_redis, DomainEventsStreamName),
        )
        cloud_accounts_redis_publisher = RedisPubSubPublisher(
            redis=readwrite_redis, channel="cloud_accounts", publisher_name="cloud_account_service"
        )
        deps.add(
            SN.cloud_account_service,
            CloudAccountServiceImpl(
                workspace_repo,
                CloudAccountRepositoryImpl(session_maker),
                cloud_accounts_redis_publisher,
                domain_event_publisher,
                LastScanRepository(session_maker),
                arq_redis,
                cfg,
                AwsAccountSetupHelper(boto_session),
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
        rw_redis = deps.add(SN.readwrite_redis, create_redis(cfg.redis_readwrite_url))
        temp_store_redis = deps.add(SN.temp_store_redis, create_redis(cfg.redis_temp_store_url))
        engine = deps.add(
            SN.async_engine,
            create_async_engine(
                cfg.database_url,
                pool_size=10,
                pool_recycle=3600,
                pool_pre_ping=True,
                # connect_args=dict(ssl=client_context)
            ),
        )
        session_maker = deps.add(SN.session_maker, async_sessionmaker(engine))
        cloud_accounts = deps.add(SN.cloud_account_repo, CloudAccountRepositoryImpl(session_maker))
        next_run_repo = deps.add(SN.next_run_repo, NextRunRepository(session_maker))
        metering_repo = deps.add(SN.metering_repo, MeteringRepository(session_maker))
        collect_queue = deps.add(SN.collect_queue, RedisCollectQueue(arq_redis))
        db_access = deps.add(SN.graph_db_access, GraphDatabaseAccessManager(cfg, session_maker))
        fixbackend_events = deps.add(
            SN.domain_event_redis_stream_publisher,
            RedisStreamPublisher(
                rw_redis,
                DomainEventsStreamName,
                "dispatching",
                keep_unprocessed_messages_for=timedelta(days=7),
            ),
        )
        domain_event_sender = deps.add(SN.domain_event_sender, DomainEventPublisherImpl(fixbackend_events))
        deps.add(
            SN.dispatching,
            DispatcherService(
                rw_redis,
                cloud_accounts,
                next_run_repo,
                metering_repo,
                collect_queue,
                db_access,
                domain_event_sender,
                temp_store_redis,
                DomainEventsStreamName,
            ),
        )

        async with deps:
            log.info("Application services started.")
            yield None
        await arq_redis.close()
        log.info("Application services stopped.")

    @asynccontextmanager
    async def setup_teardown_billing(_: FastAPI) -> AsyncIterator[None]:
        engine = deps.add(
            SN.async_engine,
            create_async_engine(
                cfg.database_url,
                pool_size=10,
                pool_recycle=3600,
                pool_pre_ping=True,
                # connect_args=dict(ssl=client_context)
            ),
        )
        session_maker = deps.add(SN.session_maker, async_sessionmaker(engine))
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
        workspace_repo = deps.add(
            SN.workspace_repo, WorkspaceRepositoryImpl(session_maker, graph_db_access, domain_event_publisher)
        )
        subscription_repo = deps.add(SN.subscription_repo, SubscriptionRepository(session_maker))
        aws_marketplace = deps.add(
            SN.aws_marketplace_handler,
            AwsMarketplaceHandler(
                subscription_repo,
                workspace_repo,
                metering_repo,
                boto_session,
                cfg.args.aws_marketplace_metering_sqs_url,
            ),
        )
        deps.add(SN.billing, BillingService(aws_marketplace, subscription_repo))

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
            # TODO: remove this option once rolled out
            if cfg.args.dispatcher:
                lifespan = setup_teardown_dispatcher
            else:
                lifespan = setup_teardown_application

    app = FastAPI(title="Fix Backend", summary="Backend for the FIX project", lifespan=lifespan)
    app.dependency_overrides[config.config] = lambda: cfg
    app.dependency_overrides[dependencies.fix_dependencies] = lambda: deps

    app.add_middleware(RealIpMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["PUT", "GET", "HEAD", "POST", "DELETE", "OPTIONS"],
        allow_headers=["X-Fix-Csrf"],
    )

    @app.exception_handler(AccessDenied)
    async def access_denied_handler(request: Request, exception: AccessDenied) -> Response:
        return JSONResponse(status_code=403, content={"message": str(exception)})

    @app.exception_handler(ResourceNotFound)
    async def resource_not_found_handler(request: Request, exception: ResourceNotFound) -> Response:
        return JSONResponse(status_code=404, content={"message": str(exception)})

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

    @app.get("/health")
    async def health() -> Response:
        return Response(status_code=200)

    @app.get("/ready")
    async def ready() -> Response:
        return Response(status_code=200)

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

    Instrumentator().instrument(app).expose(app)

    if cfg.args.mode == "app":
        api_router = APIRouter(prefix=API_PREFIX)
        api_router.include_router(auth_router(cfg, google, github), prefix="/auth", tags=["auth"])

        # organizations path is deprecated, use /workspaces instead
        api_router.include_router(workspaces_router(), prefix="/workspaces", tags=["workspaces"])
        api_router.include_router(workspaces_router(), prefix="/organizations", include_in_schema=False)  # deprecated

        api_router.include_router(cloud_accounts_router(), prefix="/workspaces", tags=["cloud_accounts"])
        api_router.include_router(
            cloud_accounts_router(), prefix="/organizations", include_in_schema=False
        )  # deprecated

        api_router.include_router(inventory_router(deps), prefix="/workspaces", tags=["inventory"])
        api_router.include_router(
            inventory_router(deps), prefix="/organizations", include_in_schema=False
        )  # deprecated

        api_router.include_router(websocket_router(cfg), prefix="/workspaces", tags=["events"])
        api_router.include_router(websocket_router(cfg), prefix="/organizations", include_in_schema=False)  # deprecated

        api_router.include_router(cloud_accounts_callback_router(), prefix="/cloud", tags=["cloud_accounts"])
        api_router.include_router(users_router(), prefix="/users", tags=["users"])
        api_router.include_router(subscription_router(deps))

        app.include_router(api_router)
        app.mount("/static", StaticFiles(directory="static"), name="static")

        cookie = cookie_transport(cfg.session_ttl)

        @app.middleware("http")
        async def refresh_session(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
            response = await call_next(request)
            if refresh_session_token := request.scope.get(refreshed_session_scope):
                # refresh the session token on every request
                cookie._set_login_cookie(response, refresh_session_token)

            return response

        if cfg.static_assets:
            app.mount("/", StaticFiles(directory=cfg.static_assets, html=True), name="static_assets")

        @app.get("/")
        async def root(request: Request) -> Response:
            body = await load_app_from_cdn()
            return Response(content=body, media_type="text/html")

        @app.exception_handler(404)
        async def not_found_handler(request: Request, exception: HTTPException) -> Response:
            if request.url.path.startswith(API_PREFIX):
                return await http_exception_handler(request, exception)
            return await root(request)

    return app


def setup_process() -> FastAPI:
    """
    This function is used by uvicorn to start the server.
    Entrypoint for the application to start the server.
    """
    current_config = config.get_config()
    level = logging.DEBUG if current_config.args.debug else logging.INFO
    setup_logger("fixbackend", level=level)

    # Replace all special uvicorn handlers
    for logger in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        lg = logging.getLogger(logger)
        lg.handlers.clear()  # remove handlers
        lg.propagate = True  # propagate to root, so the handlers there are used

    return fast_api_app(current_config)
