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

from fastapi import Request

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.auth.db import get_user_repository
from fixbackend.auth.models import User
from fixbackend.workspaces.repository import WorkspaceRepository
from fixbackend.auth.auth_backend import FixJWTStrategy
from cryptography.hazmat.primitives.asymmetric import rsa
from fixbackend.auth.user_manager import UserManager
from fixbackend.config import Config
from fixbackend.auth.user_verifier import UserVerifier
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.domain_events.events import Event


@pytest.fixture
async def user(session: AsyncSession) -> User:
    user_db = await anext(get_user_repository(session))
    user_dict = {
        "email": "foo@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    user = await user_db.create(user_dict)

    return user


class UserVerifierMock(UserVerifier):
    async def verify(self, user: User, token: str, request: Request | None) -> None:
        return None


class DomainEventSenderMock(DomainEventPublisher):
    async def publish(self, event: Event) -> None:
        pass


@pytest.mark.asyncio
async def test_token_validation(
    workspace_repository: WorkspaceRepository, user: User, default_config: Config, session: AsyncSession
) -> None:
    private_key_1 = rsa.generate_private_key(65537, 2048)
    private_key_2 = rsa.generate_private_key(65537, 2048)
    strategy1 = FixJWTStrategy([private_key_1.public_key(), private_key_2.public_key()], private_key_1, 3600)
    strategy2 = FixJWTStrategy([private_key_1.public_key(), private_key_2.public_key()], private_key_2, 3600)

    user_repo = await anext(get_user_repository(session))

    user_manager = UserManager(
        default_config, user_repo, None, UserVerifierMock(), workspace_repository, DomainEventSenderMock()
    )

    token1 = await strategy1.write_token(user)
    token2 = await strategy2.write_token(user)

    assert token1 != token2

    user1 = await strategy1.read_token(token1, user_manager)
    user2 = await strategy1.read_token(token2, user_manager)
    user3 = await strategy2.read_token(token1, user_manager)
    user4 = await strategy2.read_token(token2, user_manager)
    assert user1 == user2 == user3 == user4 == user
