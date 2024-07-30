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

import base64
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable, ClassVar, Optional, Set, Tuple, cast, AsyncIterator

from async_lru import alru_cache
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fixcloudutils.logging import setup_logger
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import select
from starlette.exceptions import HTTPException

from fixbackend import config, dependencies
from fixbackend.auth.api_token_router import api_token_router
from fixbackend.customer_support.router import admin_console_router
from fixbackend.analytics.router import analytics_router
from fixbackend.app_dependencies import create_dependencies
from fixbackend.auth.auth_backend import cookie_transport
from fixbackend.auth.depedencies import refreshed_session_scope
from fixbackend.auth.oauth_router import github_client, google_client
from fixbackend.auth.router import auth_router
from fixbackend.auth.users_router import users_router
from fixbackend.billing.router import billing_info_router
from fixbackend.cloud_accounts.router import cloud_accounts_callback_router, cloud_accounts_router
from fixbackend.config import Config
from fixbackend.dependencies import ServiceNames as SN, FixDependency, FixDependencies  # noqa
from fixbackend.errors import ClientError, NotAllowed, ResourceNotFound, WrongState
from fixbackend.events.router import websocket_router
from fixbackend.inventory.inventory_client import InventoryException
from fixbackend.inventory.inventory_router import inventory_router
from fixbackend.logging_context import get_logging_context, set_fix_cloud_account_id, set_workspace_id
from fixbackend.middleware.x_real_ip import RealIpMiddleware
from fixbackend.notification.notification_router import notification_router, unsubscribe_router
from fixbackend.permissions.router import roles_router
from fixbackend.subscription.router import subscription_router
from fixbackend.workspaces.router import workspaces_router

log = logging.getLogger(__name__)
API_PREFIX = "/api"


def dev_router(deps: FixDependencies) -> APIRouter:
    router = APIRouter()

    @router.get("/ui/{hash}", tags=["dev"], include_in_schema=False)
    async def custom_ui(hash: str) -> Response:
        app_url = f"{deps.config.cdn_endpoint}/fix-test-ui-build/{hash}/index.html"
        log.info(f"Loading dev app from CDN {app_url}")
        response = await deps.http_client.get(app_url)
        log.info("Loaded dev app from CDN")
        nonce = base64.b64encode(os.urandom(16)).decode("utf-8")
        headers: dict[str, str] = {}
        headers["fix-environment"] = deps.config.environment
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        headers["Content-Security-Policy"] = (
            "default-src 'self' https://cdn.fix.security;"
            f" connect-src 'self' data: https://capture.trackjs.com https://ph.fix.security;"
            f" script-src 'self' 'nonce-{nonce}' https://cdn.fix.security https://www.googletagmanager.com;"
            f" style-src 'self' 'nonce-{nonce}' https://cdn.fix.security;"
            " font-src 'self' data: https://cdn.fix.security;"
            " img-src 'self' data: https://cdn.fix.security https://usage.trackjs.com https://i.ytimg.com https://www.googletagmanager.com/;"
            " frame-src 'self' https://cdn.fix.security https://docs.fix.security https://www.youtube-nocookie.com;"
            " frame-ancestors 'none';"
            " form-action 'self';"
        )
        return Response(content=response.content, media_type="text/html")

    return router


# noinspection PyUnresolvedReferences
async def fast_api_app(cfg: Config, deps: FixDependencies) -> FastAPI:
    google = google_client(cfg)
    github = github_client(cfg)

    @alru_cache(maxsize=1)
    async def load_app_from_cdn() -> bytes:
        app_url = f"{cfg.frontend_cdn_origin()}/index.html"
        log.info(f"Loading app from CDN {app_url}")
        response = await deps.http_client.get(app_url)
        log.info("Loaded app from CDN")
        body = response.content
        return body

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with deps:
            log.info("Application services started.")
            yield None
        log.info("Application services stopped.")

    app = FastAPI(
        title="Fix Backend",
        summary="Backend for the Fix project",
        lifespan=lifespan,
        swagger_ui_parameters=dict(docExpansion=False, tagsSorter="alpha", operationsSorter="alpha"),
    )
    app.dependency_overrides[config.config] = lambda: cfg
    app.dependency_overrides[dependencies.fix_dependencies] = lambda: deps

    # This middleware is used to silece the error in case a client disconnect too early
    @app.middleware("http")
    async def silence_no_response_returned(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except RuntimeError as err:
            if "No response returned" in str(err):
                log.info("Client disconnected before response was returned")
                return Response(status_code=400)
            raise

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
    app.add_middleware(GZipMiddleware, compresslevel=4)  # noqa

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

    @app.exception_handler(AssertionError)
    async def invalid_data(_: Request, exception: AssertionError) -> Response:
        return JSONResponse({"detail": str(exception)}, status_code=422)

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

    @app.get("/health", tags=["system"])
    async def health() -> Response:
        try:
            pong = await deps.readwrite_redis.ping()
            if not pong:
                log.error("Redis did not respond to ping")
                return Response(status_code=500)

            async with deps.session_maker() as session:
                result = await session.execute(select(1))
                if result.scalar_one() != 1:
                    log.error("Postgres did not return 1 from select 1")
                    return Response(status_code=500)

        except Exception as e:
            log.error("Health check failed", exc_info=e)
            return Response(status_code=500)

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

    if cfg.args.mode == "support":

        @app.get("/hello")
        async def hello() -> Response:
            return Response(content="Hello, World!")

        app.include_router(admin_console_router(deps, google_client(cfg)), include_in_schema=False)

        app.mount("/static", StaticFiles(directory="static"), name="static")

    if cfg.args.mode == "app":
        api_router = APIRouter(prefix=API_PREFIX)
        api_router.include_router(auth_router(cfg, google, github), prefix="/auth", tags=["auth"])
        api_router.include_router(workspaces_router(), prefix="/workspaces", tags=["workspaces"])
        api_router.include_router(cloud_accounts_router(deps), prefix="/workspaces", tags=["cloud_accounts"])
        api_router.include_router(inventory_router(deps), prefix="/workspaces")
        api_router.include_router(websocket_router(cfg), prefix="/workspaces", tags=["events"])
        api_router.include_router(cloud_accounts_callback_router(), prefix="/cloud", tags=["cloud_accounts"])
        api_router.include_router(users_router(), prefix="/users", tags=["users"])
        api_router.include_router(subscription_router(deps), tags=["billing"])
        api_router.include_router(billing_info_router(cfg), prefix="/workspaces", tags=["billing"])
        api_router.include_router(notification_router(deps), prefix="/workspaces", tags=["notification"])
        api_router.include_router(unsubscribe_router(deps), include_in_schema=False)
        api_router.include_router(roles_router(), prefix="/workspaces", tags=["roles"])
        api_router.include_router(analytics_router(deps))
        api_router.include_router(api_token_router(deps), prefix="/token", tags=["api_token"])
        if cfg.environment == "dev":
            api_router.include_router(dev_router(deps), prefix="/dev", tags=["dev"])

        app.include_router(api_router)
        app.mount("/static", StaticFiles(directory="static"), name="static")
        cookie = cookie_transport(cfg.session_ttl)

        @app.middleware("http")
        async def refresh_session(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
            try:
                response = await call_next(request)
            except RuntimeError as err:
                if "No response returned" in str(err):
                    log.info(f"No response returned error. {request.method}: {request.url}, headers: {request.headers}")
                    return Response(status_code=500)
                raise

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
            nonce = base64.b64encode(os.urandom(16)).decode("utf-8")
            body = body.replace(b"{{ nonce }}", f"{nonce}".encode("utf-8"))
            headers: dict[str, str] = {}
            headers["fix-environment"] = cfg.environment
            headers["X-Content-Type-Options"] = "nosniff"
            headers["X-Frame-Options"] = "DENY"
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
            headers["Content-Security-Policy"] = (
                "default-src 'self' https://cdn.fix.security;"
                f" connect-src 'self' data: https://capture.trackjs.com https://ph.fix.security;"
                f" script-src 'self' 'nonce-{nonce}' https://cdn.fix.security https://www.googletagmanager.com;"
                f" style-src 'self' 'nonce-{nonce}' https://cdn.fix.security;"
                " font-src 'self' data: https://cdn.fix.security;"
                " img-src 'self' data: https://cdn.fix.security https://usage.trackjs.com https://i.ytimg.com https://www.googletagmanager.com/;"
                " frame-src 'self' https://cdn.fix.security https://docs.fix.security https://www.youtube-nocookie.com;"
                " frame-ancestors 'none';"
                " form-action 'self';"
            )
            return Response(content=body, media_type="text/html", headers=headers)

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


async def setup_fast_api() -> FastAPI:
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
    deps = await create_dependencies(current_config)
    return await fast_api_app(current_config, deps)
