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


org_id = uuid.uuid4()
external_id = uuid.uuid4()
user_id = uuid.uuid4()
user = User(id=user_id, email="foo@example.com", hashed_password="passord", is_verified=True, is_active=True)
organization = Organization(
    id=uuid.uuid4(),
    name="org name",
    slug="org-slug",
    external_id=external_id,
    tenant_id=uuid.uuid4(),
    owners=[OrganizationOwners(organization_id=org_id, user_id=user_id, user=user)],
    members=[],
)


class OrganizationServiceMock(OrganizationService):
    def __init__(self) -> None:
        pass

    async def get_organization(self, organization_id: UUID, with_users: bool = False) -> Organization | None:
        return organization

    async def list_organizations(self, owner_id: UUID, with_users: bool = False) -> Sequence[Organization]:
        return [organization]


@pytest.fixture
async def client(session: AsyncSession, default_config: Config) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app = fast_api_app(default_config)

    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_current_active_verified_user] = lambda: user
    app.dependency_overrides[get_config] = lambda: default_config
    app.dependency_overrides[get_organization_service] = lambda: OrganizationServiceMock()

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_list_organizations(client: AsyncClient) -> None:
    response = await client.get("/api/organizations/")
    assert response.json()[0] is not None


@pytest.mark.asyncio
async def test_cloudformation_link(client: AsyncClient) -> None:
    response = await client.get(f"/api/organizations/{org_id}/cf_url")
    assert response.json() == "https://example.com"


@pytest.mark.asyncio
async def test_external_id(client: AsyncClient) -> None:
    # organization is created by default
    response = await client.get(f"/api/organizations/{org_id}/external_id")
    assert response.json().get("external_id") == str(external_id)
