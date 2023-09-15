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

from fastapi import FastAPI, Request, Response

from fixbackend import config
from fixbackend.auth.oauth import github_client, google_client
from fixbackend.auth.router import auth_router, login_router
from fixbackend.config import Config
from fixbackend.organizations.router import organizations_router
from fastapi.templating import Jinja2Templates


log = logging.getLogger(__name__)


def fast_api_app(cfg: Config) -> FastAPI:
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

    templates = Jinja2Templates("fixbackend/templates")

    @app.get("/")
    async def root(request: Request) -> Response:
        cdn_origin = cfg.frontend_cdn_origin()
        return templates.TemplateResponse("index.html", {"request": request, "cdn_origin": cdn_origin})

    @app.get("/health")
    async def health() -> Response:
        return Response(status_code=200)

    @app.get("/ready")
    async def ready() -> Response:
        return Response(status_code=200)

    app.include_router(login_router(cfg, google, github), tags=["returns HTML"])
    app.include_router(auth_router(cfg, google, github), prefix="/api/auth", tags=["auth"])
    app.include_router(organizations_router(), prefix="/api/organizations", tags=["organizations"])

    return app


def setup_process() -> FastAPI:
    """
    This function is used by uvicorn to start the server.
    Entrypoint for the application to start the server.
    """
    logging.basicConfig(level=logging.INFO)
    return fast_api_app(config.get_config())
