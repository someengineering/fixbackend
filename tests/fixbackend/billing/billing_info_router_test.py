#  Copyright (c) 2023-2024. Some Engineering
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
from typing import AsyncIterator, List, Optional, Sequence, override

import pytest
from attrs import evolve
from fastapi import FastAPI
from fixcloudutils.util import utc, UTC_Date_Format
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.auth.depedencies import get_current_active_verified_user
from fixbackend.auth.models import User
from fixbackend.billing.models import PaymentMethod, PaymentMethods, WorkspacePaymentMethods, BillingEntry
from fixbackend.billing.service import BillingEntryService, get_billing_entry_service
from fixbackend.config import Config, get_config
from fixbackend.db import get_async_session
from fixbackend.ids import BillingId, ExternalId, ProductTier, SubscriptionId, UserId, WorkspaceId
from fixbackend.permissions.models import Roles, UserRole
from fixbackend.subscription.subscription_repository import SubscriptionRepository, get_subscription_repository
from fixbackend.utils import uid
from fixbackend.workspaces.dependencies import get_user_workspace
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepositoryImpl, get_workspace_repository

external_id = ExternalId(uuid.uuid4())
workspace_id = WorkspaceId(uuid.uuid4())
workspace = Workspace(workspace_id, "foo", "foo", external_id, UserId(uid()), [], ProductTier.Free, utc(), utc())
user_id = UserId(uuid.uuid4())
user = User(
    id=user_id,
    email="foo@example.com",
    hashed_password="passord",
    is_verified=True,
    is_active=True,
    is_superuser=False,
    is_mfa_active=False,
    otp_secret=None,
    oauth_accounts=[],
    roles=[UserRole(user_id, workspace_id, Roles.workspace_billing_admin)],
    created_at=utc(),
)

now = utc().replace(microsecond=0)

billing_entry = BillingEntry(
    id=BillingId(uuid.uuid4()),
    workspace_id=workspace_id,
    subscription_id=SubscriptionId(uuid.uuid4()),
    tier=ProductTier.Plus,
    nr_of_accounts_charged=42,
    period_start=now,
    period_end=now,
    reported=False,
)

sub_id = SubscriptionId(uuid.uuid4())


class BillingEntryServiceMock(BillingEntryService):
    def __init__(self) -> None:
        pass

    async def list_billing_info(self, workspace_id: WorkspaceId) -> List[BillingEntry]:
        return [billing_entry]

    async def get_payment_methods(self, workspace: Workspace, user_id: Optional[UserId]) -> WorkspacePaymentMethods:
        return WorkspacePaymentMethods(
            current=PaymentMethods.AwsSubscription(sub_id),
            available=[PaymentMethods.AwsSubscription(sub_id), PaymentMethods.NoPaymentMethod()],
        )

    async def update_billing(
        self,
        user_id: Optional[UserId],
        workspace: Workspace,
        tier: ProductTier | None = None,
        payment_method: PaymentMethod | None = None,
    ) -> Workspace:
        return workspace


class SubscriptionRepositoryMock(SubscriptionRepository):
    def __init__(self) -> None:
        pass

    async def user_has_subscription(self, user_id: UserId, subscription_id: SubscriptionId) -> bool:
        return subscription_id == sub_id


class WorkspaceRepositoryMock(WorkspaceRepositoryImpl):
    def __init__(self) -> None:
        pass

    @override
    async def get_workspace(
        self, workspace_id: WorkspaceId, *, session: Optional[AsyncSession] = None
    ) -> Workspace | None:
        return workspace

    @override
    async def list_workspaces(self, user: User, can_assign_subscriptions: bool = False) -> Sequence[Workspace]:
        return [workspace]

    @override
    async def update_workspace(self, workspace_id: WorkspaceId, name: str, generate_external_id: bool) -> Workspace:
        if generate_external_id:
            new_external_id = ExternalId(uuid.uuid4())
        else:
            new_external_id = workspace.external_id
        return evolve(workspace, name=name, external_id=new_external_id)

    @override
    async def update_product_tier(
        self, workspace_id: WorkspaceId, tier: ProductTier, *, session: AsyncSession | None = None
    ) -> Workspace:
        return evolve(workspace, product_tier=tier)

    @override
    async def update_subscription(
        self,
        workspace_id: WorkspaceId,
        subscription_id: Optional[SubscriptionId],
        *,
        session: AsyncSession | None = None,
    ) -> Workspace:
        return evolve(workspace, subscription_id=subscription_id)


@pytest.fixture
async def client(
    session: AsyncSession, default_config: Config, fast_api: FastAPI
) -> AsyncIterator[AsyncClient]:  # noqa: F811

    fast_api.dependency_overrides[get_async_session] = lambda: session
    fast_api.dependency_overrides[get_config] = lambda: default_config
    fast_api.dependency_overrides[get_user_workspace] = lambda: workspace
    fast_api.dependency_overrides[get_current_active_verified_user] = lambda: user
    fast_api.dependency_overrides[get_billing_entry_service] = lambda: BillingEntryServiceMock()
    fast_api.dependency_overrides[get_subscription_repository] = lambda: SubscriptionRepositoryMock()
    fast_api.dependency_overrides[get_workspace_repository] = lambda: WorkspaceRepositoryMock()

    async with AsyncClient(app=fast_api, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_list_billing_entries(client: AsyncClient) -> None:
    response = await client.get(f"/api/workspaces/{workspace_id}/billing_entries/")
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


@pytest.mark.asyncio
async def test_get_billing(client: AsyncClient) -> None:
    response = await client.get(f"/api/workspaces/{workspace_id}/billing")
    json = response.json()
    assert json.get("payment_method") is None
    assert json.get("workspace_payment_method") == {
        "method": "aws_marketplace",
        "subscription_id": str(sub_id),
    }
    assert json.get("available_payment_methods") == [
        {
            "method": "aws_marketplace",
            "subscription_id": str(sub_id),
        },
        {"method": "none"},
    ]
    assert response.json().get("product_tier") == "Free"


@pytest.mark.asyncio
async def test_update_billing(client: AsyncClient) -> None:
    response = await client.put(
        f"/api/workspaces/{workspace_id}/billing",
        json={
            "payment_method": "aws_marketplace",
            "workspace_payment_method": {
                "method": "aws_marketplace",
                "subscription_id": str(sub_id),
            },
            "product_tier": "Free",
        },
    )

    json = response.json()

    assert json.get("payment_method") is None
    assert json.get("workspace_payment_method") == {
        "method": "aws_marketplace",
        "subscription_id": str(sub_id),
    }
    assert json.get("product_tier") == "Free"

    # empty update does not change anything
    response = await client.put(
        f"/api/workspaces/{workspace_id}/billing",
        json={},
    )

    json = response.json()

    assert json.get("workspace_payment_method") == {
        "method": "aws_marketplace",
        "subscription_id": str(sub_id),
    }
    assert json.get("product_tier") == "Free"


@pytest.mark.asyncio
async def test_update_subscription(client: AsyncClient) -> None:
    response = await client.put(f"/api/workspaces/{workspace_id}/subscription/{sub_id}")
    assert response.status_code == 200

    unknown_subscription = SubscriptionId(uuid.uuid4())
    response = await client.put(f"/api/workspaces/{workspace_id}/subscription/{unknown_subscription}")
    assert response.status_code == 404
