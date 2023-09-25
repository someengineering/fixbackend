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
from typing import AsyncIterator

import httpx
from arq import create_pool
from arq.connections import RedisSettings
from async_lru import alru_cache
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.exceptions import HTTPException

from fixbackend import config, dependencies
from fixbackend.auth.oauth import github_client, google_client
from fixbackend.auth.router import auth_router
from fixbackend.cloud_accounts.router import cloud_accounts_router
from fixbackend.collect.collect_queue import RedisCollectQueue
from fixbackend.config import Config
from fixbackend.dependencies import FixDependencies, ServiceNames as SN
from fixbackend.events.router import websocket_router
from fixbackend.organizations.router import organizations_router

log = logging.getLogger(__name__)


def fast_api_app(cfg: Config) -> FastAPI:
    google = google_client(cfg)
    github = github_client(cfg)
    deps = FixDependencies()

    @asynccontextmanager
    async def setup_teardown_application(_: FastAPI) -> AsyncIterator[None]:
        arq_redis = deps.add(SN.arg_redis, await create_pool(RedisSettings.from_dsn(cfg.redis_queue_url)))
        deps.add(SN.async_engine, create_async_engine(cfg.database_url, pool_size=10))
        deps.add(SN.collect_queue, RedisCollectQueue(arq_redis))
        if not cfg.static_assets:
            await load_app_from_cdn()
        async with deps:
            log.info("Application services started.")
            yield None
        await arq_redis.close()
        log.info("Application services stopped.")

    app = FastAPI(
        title="Fix Backend",
        summary="Backend for the FIX project",
        description="Backend for the FIX project",
        lifespan=setup_teardown_application,
    )

    app.dependency_overrides[config.config] = lambda: cfg
    app.dependency_overrides[dependencies.fix_dependencies] = lambda: deps

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

    Instrumentator().instrument(app).expose(app)

    API_PREFIX = "/api"

    api_router = APIRouter(prefix=API_PREFIX)

    api_router.include_router(auth_router(cfg, google, github), prefix="/auth", tags=["auth"])
    api_router.include_router(organizations_router(), prefix="/organizations", tags=["organizations"])
    api_router.include_router(cloud_accounts_router(), prefix="/cloud", tags=["cloud_accounts"])

    app.include_router(api_router)
    app.include_router(websocket_router(cfg), prefix="/ws", tags=["events"])

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
    logging.basicConfig(level=logging.INFO)
    return fast_api_app(config.get_config())
