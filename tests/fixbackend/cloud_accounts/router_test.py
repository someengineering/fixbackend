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


from typing import AsyncIterator, Sequence
import uuid

from fixbackend.app import fast_api_app
from fixbackend.auth.models import User
from fixbackend.db import get_async_session
from httpx import AsyncClient
from tests.fixbackend.conftest import default_config  # noqa: F401
from tests.fixbackend.organizations.service_test import session, db_engine  # noqa: F401
from fixbackend.organizations.service import (
    get_organization_service,
    OrganizationService,
)
from fixbackend.organizations.models import Organization, OrganizationOwners
from fixbackend.config import config as get_config, Config
from fixbackend.auth.dependencies import get_current_active_verified_user
from sqlalchemy.ext.asyncio import AsyncSession
import pytest
from uuid import UUID


@pytest.fixture
async def client(session: AsyncSession, default_config: Config) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app = fast_api_app(default_config)

    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_config] = lambda: default_config

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_aws_cloudformation_callback(client: AsyncClient) -> None:
    payload = {
        "account_id": "123456789012",
        "external_id": "00000000-0000-0000-0000-000000000000",
        "role_name": "arn:aws:iam::123456789012:role/FooBarRole",
        "tenant_id": "00000000-0000-0000-0000-000000000000",
    }
    response = await client.post("/api/cloud/callbacks/aws/cf", json=payload)
    assert response.status_code == 200
