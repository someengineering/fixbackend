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

import re
import uuid
from typing import Annotated, AsyncIterator, Optional

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users.password import PasswordHelperProtocol

from fixbackend.auth.db import UserRepository, UserRepositoryDependency
from fixbackend.auth.models import User
from fixbackend.auth.user_verifier import UserVerifier, UserVerifierDependency
from fixbackend.config import Config, ConfigDependency
from fixbackend.workspaces.repository import WorkspaceRepository, WorkspaceRepositoryDependency


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    def __init__(
        self,
        config: Config,
        user_repository: UserRepository,
        password_helper: PasswordHelperProtocol | None,
        user_verifier: UserVerifier,
        workspace_repository: WorkspaceRepository,
    ):
        super().__init__(user_repository, password_helper)
        self.user_verifier = user_verifier
        self.reset_password_token_secret = config.secret
        self.verification_token_secret = config.secret
        self.workspace_repository = workspace_repository

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        if user.is_verified:  # oauth2 users are already verified
            await self.create_default_organization(user)
        else:
            await self.request_verify(user, request)

    async def on_after_request_verify(self, user: User, token: str, request: Optional[Request] = None) -> None:
        await self.user_verifier.verify(user, token, request)

    async def on_after_verify(self, user: User, request: Request | None = None) -> None:
        await self.create_default_organization(user)

    async def create_default_organization(self, user: User) -> None:
        org_slug = re.sub("[^a-zA-Z0-9-]", "-", user.email)
        await self.workspace_repository.create_workspace(user.email, org_slug, user)


async def get_user_manager(
    config: ConfigDependency,
    user_repository: UserRepositoryDependency,
    user_verifier: UserVerifierDependency,
    workspace_repository: WorkspaceRepositoryDependency,
) -> AsyncIterator[UserManager]:
    yield UserManager(config, user_repository, None, user_verifier, workspace_repository)


UserManagerDependency = Annotated[UserManager, Depends(get_user_manager)]
