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
import secrets
from typing import Annotated, Any, AsyncIterator, Optional
from uuid import UUID

import pyotp
from fastapi import Depends, Request
from fastapi_users import BaseUserManager, exceptions
from fastapi_users.password import PasswordHelperProtocol
from starlette.responses import Response

from fixbackend.auth.models import User
from fixbackend.auth.schemas import OTPConfig
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
    ):
        super().__init__(user_repository, password_helper)
        self.user_repository = user_repository
        self.auth_email_sender = auth_email_sender
        self.reset_password_token_secret = config.secret
        self.verification_token_secret = config.secret
        self.workspace_repository = workspace_repository
        self.domain_events_publisher = domain_events_publisher
        self.invitation_repository = invitation_repository

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
        return user

    async def get_by_email(self, user_email: str) -> User:
        user = await super().get_by_email(user_email)
        return user

    async def get_by_oauth_account(self, oauth: str, account_id: str) -> User:
        user = await super().get_by_oauth_account(oauth, account_id)
        return user

    async def oauth_callback(
        self,
        oauth_name: str,
        access_token: str,
        account_id: str,
        account_email: str,
        expires_at: Optional[int] = None,
        refresh_token: Optional[str] = None,
        request: Optional[Request] = None,
        *,
        associate_by_email: bool = False,
        is_verified_by_default: bool = False,
        username: Optional[str] = None,
    ) -> User:
        oauth_account_dict = {
            "oauth_name": oauth_name,
            "access_token": access_token,
            "account_id": account_id,
            "account_email": account_email,
            "expires_at": expires_at,
            "refresh_token": refresh_token,
        }
        if username:
            oauth_account_dict["username"] = username

        try:
            user = await self.get_by_oauth_account(oauth_name, account_id)
        except exceptions.UserNotExists:
            try:
                # Associate account
                user = await self.get_by_email(account_email)
                if not associate_by_email:
                    raise exceptions.UserAlreadyExists()
                user = await self.user_db.add_oauth_account(user, oauth_account_dict)
            except exceptions.UserNotExists:
                # Create account
                password = self.password_helper.generate()
                user_dict = {
                    "email": account_email,
                    "hashed_password": self.password_helper.hash(password),
                    "is_verified": is_verified_by_default,
                }
                user = await self.user_db.create(user_dict)
                user = await self.user_db.add_oauth_account(user, oauth_account_dict)
                await self.on_after_register(user, request)
        else:
            # Update oauth
            for existing_oauth_account in user.oauth_accounts:
                if existing_oauth_account.account_id == account_id and existing_oauth_account.oauth_name == oauth_name:
                    user = await self.user_db.update_oauth_account(user, existing_oauth_account, oauth_account_dict)

        return user

    async def oauth_associate_callback(
        self,
        user: User,
        oauth_name: str,
        access_token: str,
        account_id: str,
        account_email: str,
        expires_at: Optional[int] = None,
        refresh_token: Optional[str] = None,
        request: Optional[Request] = None,
        username: Optional[str] = None,
    ) -> User:
        oauth_account_dict = {
            "oauth_name": oauth_name,
            "access_token": access_token,
            "account_id": account_id,
            "account_email": account_email,
            "expires_at": expires_at,
            "refresh_token": refresh_token,
        }

        if username:
            oauth_account_dict["username"] = username

        user = await self.user_db.add_oauth_account(user, oauth_account_dict)

        await self.on_after_update(user, {}, request)

        return user

    async def recreate_mfa(self, user: User) -> OTPConfig:
        assert not user.is_mfa_active, "User already has MFA enabled."
        user_secret = pyotp.random_base32()
        # create recovery codes
        recovery_codes = [secrets.token_hex(16) for _ in range(10)]
        # create hashes of the recovery codes
        hashes = [self.password_helper.hash(code) for code in recovery_codes]
        await self.user_repository.recreate_otp_secret(user.id, user_secret, is_mfa_active=False, hashes=hashes)
        # return the OTP Config
        return OTPConfig(secret=user_secret, recovery_codes=recovery_codes)

    async def enable_mfa(self, user: User, otp: str) -> bool:
        assert not user.is_mfa_active, "User already has MFA enabled."
        if (secret := user.otp_secret) and not pyotp.TOTP(secret).verify(otp, valid_window=1):
            return False
        await self.user_repository.update(user, {"is_mfa_active": True})
        return True

    async def disable_mfa(self, user: User, otp: Optional[str], recovery_code: Optional[str]) -> bool:
        if not user.is_mfa_active:
            return True
        if await self.check_otp(user, otp, recovery_code):
            await self.user_repository.update(user, {"is_mfa_active": False, "otp_secret": None})
            return True
        return False

    async def check_otp(self, user: User, otp: Optional[str], recovery_code: Optional[str]) -> bool:
        if not user.is_mfa_active:
            return True
        if (secret := user.otp_secret) and (otp_defined := otp):
            return pyotp.TOTP(secret).verify(otp_defined)
        if recovery_code:
            return await self.user_repository.delete_recovery_code(user.id, recovery_code, self.password_helper)
        return False


async def get_user_manager(
    config: ConfigDependency,
    user_repository: UserRepositoryDependency,
    user_verifier: AuthEmailSenderDependency,
    workspace_repository: WorkspaceRepositoryDependency,
    domain_event_publisher: DomainEventPublisherDependency,
    invitation_repository: InvitationRepositoryDependency,
) -> AsyncIterator[UserManager]:
    yield UserManager(
        config,
        user_repository,
        None,
        user_verifier,
        workspace_repository,
        domain_event_publisher,
        invitation_repository,
    )


UserManagerDependency = Annotated[UserManager, Depends(get_user_manager)]
