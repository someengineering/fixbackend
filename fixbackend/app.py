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
from fastapi import FastAPI, Request, Response
from prometheus_fastapi_instrumentator import Instrumentator

from fixbackend import config
from fixbackend.auth.oauth import github_client, google_client
from fixbackend.auth.router import auth_router
from fixbackend.collect.collect_queue import RedisCollectQueue
from fixbackend.config import Config
from fixbackend.organizations.router import organizations_router
from fixbackend.cloud_accounts.router import cloud_accounts_router
from fixbackend.events.router import websocket_router
from fastapi.staticfiles import StaticFiles


log = logging.getLogger(__name__)


def fast_api_app(cfg: Config) -> FastAPI:
    google = google_client(cfg)
    github = github_client(cfg)

    @asynccontextmanager
    async def setup_teardown_application(_: FastAPI) -> AsyncIterator[None]:
        arq_redis = await create_pool(RedisSettings.from_dsn(cfg.redis_queue_url))
        RedisCollectQueue(arq_redis)
        if not cfg.static_assets:
            await load_app_from_cdn()
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
    app.include_router(auth_router(cfg, google, github), prefix="/api/auth", tags=["auth"])
    app.include_router(organizations_router(), prefix="/api/organizations", tags=["organizations"])
    app.include_router(cloud_accounts_router(), prefix="/api/cloud", tags=["cloud_accounts"])
    app.include_router(websocket_router(cfg), prefix="/ws", tags=["events"])

    if cfg.static_assets:
        app.mount("/", StaticFiles(directory=cfg.static_assets, html=True), name="static_assets")

    @app.get("/")
    async def root(request: Request) -> Response:
        body = await load_app_from_cdn()
        return Response(content=body, media_type="text/html")

    return app


def setup_process() -> FastAPI:
    """
    This function is used by uvicorn to start the server.
    Entrypoint for the application to start the server.
    """
    logging.basicConfig(level=logging.INFO)
    return fast_api_app(config.get_config())
