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


import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from fixbackend.auth.depedencies import get_current_active_verified_user
from fixbackend.auth.models import User
from fixbackend.config import Config, get_config
from typing import AsyncIterator, List
from fixbackend.app import fast_api_app
from fixbackend.db import get_async_session
from fixbackend.ids import BillingId, ExternalId, SecurityTier, SubscriptionId, UserId, WorkspaceId
from fixbackend.billing_information.service import BillingEntryService, get_billing_entry_service
from fixbackend.subscription.models import BillingEntry
from fixbackend.workspaces.dependencies import get_user_workspace
from fixbackend.workspaces.models import Workspace
from fixcloudutils.util import utc, UTC_Date_Format

external_id = ExternalId(uuid.uuid4())
workspace_id = WorkspaceId(uuid.uuid4())
workspace = Workspace(workspace_id, "foo", "foo", external_id, [], [], SecurityTier.Free)
user_id = UserId(uuid.uuid4())
user = User(
    id=user_id,
    email="foo@example.com",
    hashed_password="passord",
    is_verified=True,
    is_active=True,
    is_superuser=False,
    oauth_accounts=[],
)

now = utc().replace(microsecond=0)

billing_entry = BillingEntry(
    id=BillingId(uuid.uuid4()),
    workspace_id=workspace_id,
    subscription_id=SubscriptionId(uuid.uuid4()),
    tier=SecurityTier.Foundational,
    nr_of_accounts_charged=42,
    period_start=now,
    period_end=now,
    reported=False,
)


class BillingEntryServiceMock(BillingEntryService):
    def __init__(self) -> None:
        pass

    async def list_billing_info(self, workspace_id: WorkspaceId) -> List[BillingEntry]:
        return [billing_entry]


@pytest.fixture
async def client(session: AsyncSession, default_config: Config) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app = fast_api_app(default_config)

    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_config] = lambda: default_config
    app.dependency_overrides[get_user_workspace] = lambda: workspace
    app.dependency_overrides[get_current_active_verified_user] = lambda: user
    app.dependency_overrides[get_billing_entry_service] = lambda: BillingEntryServiceMock()

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_list_billing_entries(client: AsyncClient) -> None:
    response = await client.get("/api/workspaces/{workspace_id}/billing_entries/")
    assert response.status_code == 200
    assert len(response.json()) == 1
    json_billing_entry = response.json()[0]
    assert json_billing_entry["id"] == str(billing_entry.id)
    assert json_billing_entry["workspace_id"] == str(billing_entry.workspace_id)
    assert json_billing_entry["subscription_id"] == str(billing_entry.subscription_id)
    assert json_billing_entry["tier"] == billing_entry.tier.value
    assert json_billing_entry["period_start"] == billing_entry.period_start.strftime(UTC_Date_Format)
    assert json_billing_entry["period_end"] == billing_entry.period_end.strftime(UTC_Date_Format)
    assert json_billing_entry["nr_of_accounts_charged"] == billing_entry.nr_of_accounts_charged
