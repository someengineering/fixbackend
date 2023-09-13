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

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from fixbackend import config
from fixbackend.auth.oauth import github_client, google_client
from fixbackend.auth.router import auth_router, login_router
from fixbackend.organizations.router import organizations_router

log = logging.getLogger(__name__)


def fast_api_app() -> FastAPI:
    cfg = config.get_config()
    google = google_client(cfg)
    github = github_client(cfg)

    @asynccontextmanager
    async def setup_teardown_application(_: FastAPI) -> AsyncIterator[None]:
        log.info("Application services started.")
        yield None
        log.info("Application services stopped.")

    app = FastAPI(
        title="Fix Backend",
        summary="Backend for the FIX project",
        description="Backend for the FIX project",
        lifespan=setup_teardown_application,
    )

    app.dependency_overrides[config.config] = lambda: cfg

    app.include_router(login_router(cfg, google, github), tags=["returns HTML"])
    app.include_router(auth_router(cfg, google, github), prefix="/api/auth", tags=["auth"])
    app.include_router(organizations_router(), prefix="/api/organizations", tags=["organizations"])
    app.mount("/", StaticFiles(directory="fixbackend/static", html=True), name="static")

    @app.get("/health")
    async def health() -> Response:
        return Response(status_code=200)

    @app.get("/ready")
    async def ready() -> Response:
        return Response(status_code=200)

    return app


def setup_process() -> FastAPI:
    """
    This function is used by uvicorn to start the server.
    Entrypoint for the application to start the server.
    """
    logging.basicConfig(level=logging.INFO)
    return fast_api_app()
