from typing import AsyncIterator, List, Tuple
from fixbackend.app import app
from fixbackend.auth.models import User
from fixbackend.db import get_async_session
from httpx import AsyncClient
from tests.fixbackend.organizations.service_test import session, db_engine  # noqa: F401
from fixbackend.auth.user_verifyer import UserVerifyer, get_user_verifyer

from sqlalchemy.ext.asyncio import AsyncSession
import pytest


class InMemoryVerifyer(UserVerifyer):
    def __init__(self) -> None:
        self.verification_requests: List[Tuple[User, str]] = []

    async def verify(self, user: User, token: str) -> None:
        return self.verification_requests.append((user, token))


verifyer = InMemoryVerifyer()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_user_verifyer] = lambda: verifyer

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_registration_flow(client: AsyncClient) -> None:
    registration_json = {
        "email": "user@example.com",
        "password": "changeme",
    }

    # register user
    response = await client.post("/auth/register", json=registration_json)
    assert response.status_code == 201

    login_json = {
        "username": registration_json["email"],
        "password": registration_json["password"],
    }

    # non_verifyed can't login
    response = await client.post("/auth/jwt/login", data=login_json)
    assert response.status_code == 400

    # verify user
    user, token = verifyer.verification_requests[0]
    verification_json = {
        "token": token,
    }
    response = await client.post("/auth/verify", json=verification_json)
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["email"] == user.email
    assert response_json["is_superuser"] is False
    assert response_json["is_verified"] is True
    assert response_json["is_active"] is True
    assert response_json["id"] == str(user.id)

    # verifyed can login
    response = await client.post("/auth/jwt/login", data=login_json)
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["access_token"] is not None
