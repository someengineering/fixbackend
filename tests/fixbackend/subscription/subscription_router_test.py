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


from types import SimpleNamespace
from typing import AsyncIterator, Dict, Optional, Tuple, override
import uuid
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.config import Config, get_config
from fixbackend.app import fast_api_app
from fixbackend.auth.depedencies import maybe_current_active_verified_user
from fixbackend.auth.models import User
from fixbackend.db import get_async_session
import pytest

from fixbackend.ids import SubscriptionId, UserId, WorkspaceId
from fixbackend.subscription.aws_marketplace import AwsMarketplaceHandler, get_marketplace_handler
from fixbackend.subscription.models import SubscriptionMethod

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
    roles=[],
)

subscription = SimpleNamespace(
    id=SubscriptionId(uuid.uuid4()),
    workspace_id=WorkspaceId(uuid.uuid4()),
)

current_user: Optional[User] = user


def set_user(u: Optional[User]) -> None:
    global current_user
    current_user = u


def get_user() -> Optional[User]:
    return current_user


class AwsMarketplaceHandlerMock(AwsMarketplaceHandler):
    def __init__(self) -> None:
        self.subcriptions: Dict[UserId, SubscriptionMethod] = {user.id: subscription}  # type: ignore

    @override
    async def subscribed(self, user: User, token: str) -> Tuple[SubscriptionMethod, bool]:
        return self.subcriptions[user.id], False


handler = AwsMarketplaceHandlerMock()


@pytest.fixture
async def client(session: AsyncSession, default_config: Config) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app = fast_api_app(default_config)
    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[maybe_current_active_verified_user] = get_user
    app.dependency_overrides[get_config] = lambda: default_config
    app.dependency_overrides[get_marketplace_handler] = lambda: handler

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_aws_marketplace_fulfillment_after_login(client: AsyncClient) -> None:
    response = await client.get("/api/subscriptions/aws/marketplace/add", cookies={"fix-aws-marketplace-token": "foo"})
    assert response.status_code == 307
    assert response.headers["location"] == f"/subscription/choose-workspace?subscription_id={subscription.id}"


@pytest.mark.asyncio
async def test_fulfillment_after_login_no_user(client: AsyncClient) -> None:
    set_user(None)
    response = await client.get("/api/subscriptions/aws/marketplace/add", cookies={"fix-aws-marketplace-token": "foo"})
    assert response.status_code == 307
    assert response.headers["location"] == "/auth/login?returnUrl=/api/subscriptions/aws/marketplace/add"
    set_user(user)


@pytest.mark.asyncio
async def test_aws_marketplace_fulfillment_no_workspace_id(client: AsyncClient) -> None:
    handler.subcriptions[user.id] = SimpleNamespace(id=subscription.id, workspace_id=None)  # type: ignore
    response = await client.get("/api/subscriptions/aws/marketplace/add", cookies={"fix-aws-marketplace-token": "foo"})
    assert response.status_code == 307
    assert response.headers["location"] == f"/subscription/choose-workspace?subscription_id={subscription.id}"
