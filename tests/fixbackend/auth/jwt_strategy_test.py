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

from typing import Optional, override, List
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Request

from fixbackend.certificates.cert_store import CertificateStore
from fixbackend.types import AsyncSessionMaker

from fixbackend.auth.auth_backend import FixJWTStrategy
from fixbackend.auth.models import User
from fixbackend.auth.user_manager import UserManager
from fixbackend.auth.user_repository import get_user_repository
from fixbackend.auth.user_verifier import AuthEmailSender
from fixbackend.config import Config
from fixbackend.domain_events.events import Event
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.workspaces.invitation_repository import InvitationRepository
from fixbackend.workspaces.repository import WorkspaceRepository


@pytest.fixture
async def user(async_session_maker: AsyncSessionMaker) -> User:
    user_db = await anext(get_user_repository(async_session_maker))
    user_dict = {
        "email": "foo@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    user = await user_db.create(user_dict)

    return user


# noinspection PyMissingConstructor
class AuthEmailSenderMock(AuthEmailSender):
    def __init__(self) -> None:
        pass

    @override
    async def send_verify_email(self, user: User, token: str, request: Optional[Request]) -> None:
        pass

    @override
    async def send_password_reset(self, user: User, token: str, request: Optional[Request]) -> None:
        pass


class DomainEventSenderMock(DomainEventPublisher):
    async def publish(self, event: Event) -> None:
        pass


# noinspection PyMissingConstructor
class CertificateStoreMock(CertificateStore):
    def __init__(self, public_keys: List[rsa.RSAPublicKey], private_key: rsa.RSAPrivateKey) -> None:
        self.private_key_direct = private_key
        self.public_keys_direct = public_keys

    async def private_key(self) -> rsa.RSAPrivateKey:
        return self.private_key_direct

    async def public_keys(self) -> List[rsa.RSAPublicKey]:
        return self.public_keys_direct


@pytest.mark.asyncio
async def test_token_validation(
    workspace_repository: WorkspaceRepository,
    user: User,
    default_config: Config,
    async_session_maker: AsyncSessionMaker,
    invitation_repository: InvitationRepository,
) -> None:
    private_key_1 = rsa.generate_private_key(65537, 2048)
    private_key_2 = rsa.generate_private_key(65537, 2048)
    strategy1 = FixJWTStrategy(
        CertificateStoreMock([private_key_1.public_key(), private_key_2.public_key()], private_key_1), 3600
    )
    strategy2 = FixJWTStrategy(
        CertificateStoreMock([private_key_1.public_key(), private_key_2.public_key()], private_key_2), 3600
    )

    user_repo = await anext(get_user_repository(async_session_maker))

    user_manager = UserManager(
        default_config,
        user_repo,
        None,
        AuthEmailSenderMock(),
        workspace_repository,
        DomainEventSenderMock(),
        invitation_repository,
    )

    token1 = await strategy1.write_token(user)
    token2 = await strategy2.write_token(user)

    assert token1 != token2

    user1 = await strategy1.read_token(token1, user_manager)
    user2 = await strategy1.read_token(token2, user_manager)
    user3 = await strategy2.read_token(token1, user_manager)
    user4 = await strategy2.read_token(token2, user_manager)
    assert user1 == user2 == user3 == user4 == user

    # decoding invalid token returns None
    assert await strategy1.decode_token("invalid token") is None
