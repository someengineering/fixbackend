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

from typing import AsyncIterator, List, Tuple, Optional
from fixbackend.app import fast_api_app
from fixbackend.auth.models import User
from tests.fixbackend.conftest import default_config  # noqa: F401
from fixbackend.db import get_async_session
from httpx import AsyncClient
from tests.fixbackend.organizations.service_test import session, db_engine  # noqa: F401
from fixbackend.auth.user_verifier import UserVerifier, get_user_verifier
from fixbackend.config import config as get_config, Config
from sqlalchemy.ext.asyncio import AsyncSession
import pytest
from fastapi import Request


class InMemoryVerifier(UserVerifier):
    def __init__(self) -> None:
        self.verification_requests: List[Tuple[User, str]] = []

    async def verify(self, user: User, token: str, request: Optional[Request]) -> None:
        return self.verification_requests.append((user, token))


verifier = InMemoryVerifier()


@pytest.fixture
async def client(session: AsyncSession, default_config: Config) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app = fast_api_app(default_config)
    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_user_verifier] = lambda: verifier
    app.dependency_overrides[get_config] = lambda: default_config

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_registration_flow(client: AsyncClient) -> None:
    registration_json = {
        "email": "user@example.com",
        "password": "changeme",
    }

    # register user
    response = await client.post("/api/auth/register", json=registration_json)
    assert response.status_code == 201

    login_json = {
        "username": registration_json["email"],
        "password": registration_json["password"],
    }

    # non_verified can't login
    response = await client.post("/api/auth/jwt/login", data=login_json)
    assert response.status_code == 400

    # verify user
    user, token = verifier.verification_requests[0]
    verification_json = {
        "token": token,
    }
    response = await client.post("/api/auth/verify", json=verification_json)
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["email"] == user.email
    assert response_json["is_superuser"] is False
    assert response_json["is_verified"] is True
    assert response_json["is_active"] is True
    assert response_json["id"] == str(user.id)

    # verified can login
    response = await client.post("/api/auth/jwt/login", data=login_json)
    assert response.status_code == 204
    response_cookies = response.cookies
    assert response_cookies.get("fix.auth") is not None
