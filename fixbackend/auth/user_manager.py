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

import asyncio
import logging
import re
import secrets
from concurrent.futures import ProcessPoolExecutor
from typing import Annotated, Any, Optional, Tuple, Union
from uuid import UUID

import fastapi_users
import pyotp
from fastapi import Depends, Request
from fastapi_users import BaseUserManager, exceptions
from fastapi_users.password import PasswordHelperProtocol, PasswordHelper
from fixcloudutils.util import utc
from passlib.context import CryptContext
from starlette.responses import Response

from fixbackend.auth.models import User
from fixbackend.auth.schemas import OTPConfig, UserCreate, UserUpdate
from fixbackend.auth.user_repository import UserRepository
from fixbackend.auth.user_verifier import AuthEmailSender
from fixbackend.config import Config
from fixbackend.dependencies import FixDependency, ServiceNames
from fixbackend.domain_events.events import UserLoggedIn, UserRegistered
from fixbackend.domain_events.publisher import DomainEventPublisher
from fixbackend.ids import UserId
from fixbackend.workspaces.invitation_repository import InvitationRepository
from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository

# do not change this without regenerating MFA recovery codes in the db
crypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
log = logging.getLogger(__name__)


def bcrypt_hash(password: str) -> str:
    return crypt_context.hash(password)  # type: ignore


blocking_cpu_executor = ProcessPoolExecutor()


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
        self.custom_password_helper = password_helper is not None
        self.otp_valid_window = 1

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
        log.info(f"User logged in: {user.email} ({user.id})")
        await self.domain_events_publisher.publish(UserLoggedIn(user.id, user.email))
        now = utc()
        await self.user_repository.update_partial(user.id, last_active=now, last_login=now)

    async def add_to_workspace(self, user: User) -> None:
        if (
            pending_invitation := await self.invitation_repository.get_invitation_by_email(user.email)
        ) and pending_invitation.accepted_at:
            if workspace := await self.workspace_repository.get_workspace(pending_invitation.workspace_id):
                log.info(f"Add user {user.email} to workspace {workspace.id}")
                await self.workspace_repository.add_to_workspace(workspace.id, user.id, pending_invitation.role)
            else:
                # wtf?
                workspace = await self.create_default_workspace(user)
            await self.invitation_repository.delete_invitation(workspace.id, pending_invitation.id)
        else:
            workspace = await self.create_default_workspace(user)
            log.info(f"Create new workspace {workspace.id} for {user.email}.")

        await self.domain_events_publisher.publish(
            UserRegistered(user_id=user.id, email=user.email, tenant_id=workspace.id)
        )

    async def create_default_workspace(self, user: User) -> Workspace:
        org_slug = re.sub("[^a-zA-Z0-9-]", "-", user.email)
        return await self.workspace_repository.create_workspace(user.email, org_slug, user)

    async def remove_oauth_account(self, account_id: UUID) -> None:
        log.info(f"Remove oauth account with id {account_id}")
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

    async def compute_recovery_codes(self) -> Tuple[list[str], list[str]]:
        # use custom password helper if provided, e.g. for testing
        if self.custom_password_helper:
            recovery_codes = [secrets.token_hex(16) for _ in range(10)]
            hashes = [self.password_helper.hash(code) for code in recovery_codes]
            return recovery_codes, hashes

        # create recovery codes
        recovery_codes = [secrets.token_hex(16) for _ in range(10)]
        # create hashes of the recovery codes
        hashes = []
        loop = asyncio.get_event_loop()
        async with asyncio.TaskGroup() as tg:
            for code in recovery_codes:

                async def compute_hash(code: str) -> None:
                    result = await loop.run_in_executor(blocking_cpu_executor, bcrypt_hash, code)
                    hashes.append(result)

                tg.create_task(compute_hash(code))

        return recovery_codes, hashes

    async def recreate_mfa(self, user: User) -> OTPConfig:
        log.info(f"Recreate MFA for user {user.email}")
        assert not user.is_mfa_active, "User already has MFA enabled."
        user_secret = pyotp.random_base32()
        # create recovery codes
        recovery_codes, hashes = await self.compute_recovery_codes()
        await self.user_repository.recreate_otp_secret(user.id, user_secret, is_mfa_active=False, hashes=hashes)
        # return the OTP Config
        return OTPConfig(secret=user_secret, recovery_codes=recovery_codes)

    async def enable_mfa(self, user: User, otp: str) -> bool:
        log.info(f"Enable MFA for user {user.email}")
        assert not user.is_mfa_active, "User already has MFA enabled."
        if (secret := user.otp_secret) and not pyotp.TOTP(secret).verify(otp, valid_window=self.otp_valid_window):
            return False
        await self.user_repository.update(user, {"is_mfa_active": True})
        return True

    async def disable_mfa(self, user: User, otp: Optional[str], recovery_code: Optional[str]) -> bool:
        log.info(f"Disable MFA for user {user.email}")
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
            return pyotp.TOTP(secret).verify(otp_defined, valid_window=self.otp_valid_window)
        if recovery_code:
            return await self.user_repository.delete_recovery_code(user.id, recovery_code, self.password_helper)
        return False

    async def validate_password(self, password: str, user: Union[UserCreate, User]) -> None:  # type: ignore
        if len(password) < 16:
            raise fastapi_users.InvalidPasswordException(reason="Password is too short. Minimum length: 16 characters.")

        if not re.search(r"[A-Z]", password):
            raise fastapi_users.InvalidPasswordException(reason="Password must contain at least one uppercase letter.")

        if not re.search(r"[a-z]", password):
            raise fastapi_users.InvalidPasswordException(reason="Password must contain at least one lowercase letter.")

        if not re.search(r"[0-9]", password):
            raise fastapi_users.InvalidPasswordException(reason="Password must contain at least one digit.")

    async def update(
        self,
        user_update: UserUpdate,  # type: ignore
        user: User,
        safe: bool = False,
        request: Optional[Request] = None,
    ) -> User:
        if user_update.password:
            if not user_update.current_password:
                raise exceptions.InvalidPasswordException(reason="Current password is required to update password.")

            verified, _ = self.password_helper.verify_and_update(user_update.current_password, user.hashed_password)

            if not verified:
                raise exceptions.InvalidPasswordException(reason="Current password is incorrect.")

        return await super().update(user_update, user, safe)


def get_password_helper(deps: FixDependency) -> PasswordHelperProtocol | None:
    return deps.service(ServiceNames.password_helper, PasswordHelper)


PasswordHelperDependency = Annotated[PasswordHelperProtocol | None, Depends(get_password_helper)]


async def get_user_manager(fix_deps: FixDependency) -> UserManager:
    return fix_deps.service(ServiceNames.user_manager, UserManager)


UserManagerDependency = Annotated[UserManager, Depends(get_user_manager)]
