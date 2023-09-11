from typing import AsyncIterator
from fixbackend.app import app
from fixbackend.db import get_async_session
from httpx import AsyncClient
from tests.fixbackend.organizations.service_test import session, db_engine  # noqa: F401

# from tests.fixbackend.conftest import event_loop  # noqa: F401

from sqlalchemy.ext.asyncio import AsyncSession
import pytest


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app.dependency_overrides[get_async_session] = lambda: session

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_register(client: AsyncClient) -> None:
    user_data = {
        "email": "user@example.com",
        "password": "changeme",
    }
    response = await client.post("/auth/register", json=user_data)

    response_json = response.json()
    assert response.status_code == 201
    assert response_json["email"] == user_data["email"]
    assert response_json["is_superuser"] is False
    assert response_json["is_verified"] is False
