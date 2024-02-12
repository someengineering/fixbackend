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
from typing import Annotated, Any, AsyncIterator, Optional
from uuid import UUID

from attrs import evolve
from fastapi import Depends, Request
from fastapi_users import BaseUserManager, exceptions
from fastapi_users.password import PasswordHelperProtocol
from starlette.responses import Response

from fixbackend.auth.models import User
from fixbackend.auth.role_repository import RoleRepository, RoleRepositoryDependency
from fixbackend.auth.user_repository import UserRepository, UserRepositoryDependency
from fixbackend.auth.user_verifier import AuthEmailSender, AuthEmailSenderDependency
from fixbackend.config import Config, ConfigDependency
from fixbackend.domain_events.dependencies import DomainEventPublisherDependency
from fixbackend.domain_events.events import UserLoggedIn, UserRegistered
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.ids import UserId
from fixbackend.workspaces.invitation_repository import InvitationRepository, InvitationRepositoryDependency
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository, WorkspaceRepositoryDependency


class UserManager(BaseUserManager[User, UserId]):
    def __init__(
        self,
        config: Config,
        user_repository: UserRepository,
        password_helper: PasswordHelperProtocol | None,
        auth_email_sender: AuthEmailSender,
        workspace_repository: WorkspaceRepository,
        domain_events_publisher: DomainEventPublisher,
        invitation_repository: InvitationRepository,
        role_repository: RoleRepository,
    ):
        super().__init__(user_repository, password_helper)
        self.user_repository = user_repository
        self.auth_email_sender = auth_email_sender
        self.reset_password_token_secret = config.secret
        self.verification_token_secret = config.secret
        self.workspace_repository = workspace_repository
        self.domain_events_publisher = domain_events_publisher
        self.invitation_repository = invitation_repository
        self.role_repository = role_repository

    def parse_id(self, value: Any) -> UserId:
        if isinstance(value, UUID):
            return UserId(value)
        try:
            return UserId(UUID(value))
        except ValueError as e:
            raise exceptions.InvalidID() from e

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        if user.is_verified:  # oauth2 users are already verified
            await self.add_to_workspace(user)
        else:
            await self.request_verify(user, request)

    async def on_after_request_verify(self, user: User, token: str, request: Optional[Request] = None) -> None:
        await self.auth_email_sender.send_verify_email(user, token, request)

    async def on_after_verify(self, user: User, request: Request | None = None) -> None:
        await self.add_to_workspace(user)

    async def on_after_forgot_password(self, user: User, token: str, request: Request | None = None) -> None:
        await self.auth_email_sender.send_password_reset(user, token, request)

    async def on_after_login(
        self, user: User, request: Optional[Request] = None, response: Optional[Response] = None
    ) -> None:
        await super().on_after_login(user, request, response)
        await self.domain_events_publisher.publish(UserLoggedIn(user.id, user.email))

    async def add_to_workspace(self, user: User) -> None:
        if (
            pending_invitation := await self.invitation_repository.get_invitation_by_email(user.email)
        ) and pending_invitation.accepted_at:
            if workspace := await self.workspace_repository.get_workspace(pending_invitation.workspace_id):
                await self.workspace_repository.add_to_workspace(workspace.id, user.id)
            else:
                # wtf?
                workspace = await self.create_default_workspace(user)
            await self.invitation_repository.delete_invitation(pending_invitation.id)
        else:
            workspace = await self.create_default_workspace(user)

        await self.domain_events_publisher.publish(
            UserRegistered(user_id=user.id, email=user.email, tenant_id=workspace.id)
        )

    async def create_default_workspace(self, user: User) -> Workspace:
        org_slug = re.sub("[^a-zA-Z0-9-]", "-", user.email)
        return await self.workspace_repository.create_workspace(user.email, org_slug, user)

    async def remove_oauth_account(self, account_id: UUID) -> None:
        await self.user_repository.remove_oauth_account(account_id)

    async def get(self, id: UserId) -> User:
        user = await super().get(id)
        roles = await self.role_repository.list_roles(user.id)
        user = evolve(user, roles=roles)
        return user

    async def get_by_email(self, user_email: str) -> User:
        user = await super().get_by_email(user_email)
        roles = await self.role_repository.list_roles(user.id)
        user = evolve(user, roles=roles)
        return user

    async def get_by_oauth_account(self, oauth: str, account_id: str) -> User:
        user = await super().get_by_oauth_account(oauth, account_id)
        roles = await self.role_repository.list_roles(user.id)
        user = evolve(user, roles=roles)
        return user


async def get_user_manager(
    config: ConfigDependency,
    user_repository: UserRepositoryDependency,
    user_verifier: AuthEmailSenderDependency,
    workspace_repository: WorkspaceRepositoryDependency,
    domain_event_publisher: DomainEventPublisherDependency,
    invitation_repository: InvitationRepositoryDependency,
    role_repository: RoleRepositoryDependency,
) -> AsyncIterator[UserManager]:
    yield UserManager(
        config,
        user_repository,
        None,
        user_verifier,
        workspace_repository,
        domain_event_publisher,
        invitation_repository,
        role_repository,
    )


UserManagerDependency = Annotated[UserManager, Depends(get_user_manager)]
