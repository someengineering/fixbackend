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
from logging import getLogger
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, Form
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users.authentication import AuthenticationBackend, Strategy
from fastapi_users.router import ErrorCode
from fastapi_users.router.oauth import generate_state_token
from httpx_oauth.clients.google import GoogleOAuth2
from httpx_oauth.oauth2 import BaseOAuth2

from fixbackend.auth.auth_backend import get_auth_backend, FixJWTStrategy
from fixbackend.auth.depedencies import AuthenticatedUser, fastapi_users
from fixbackend.auth.models import User
from fixbackend.auth.oauth_clients import GithubOauthClient
from fixbackend.auth.oauth_router import get_oauth_associate_router, get_oauth_router
from fixbackend.auth.schemas import OAuthProviderAssociateUrl, OAuthProviderAuthUrl, UserCreate, UserRead, OTPConfig
from fixbackend.auth.user_manager import UserManagerDependency, UserManager, get_user_manager
from fixbackend.config import Config
from fixbackend.ids import UserId

log = getLogger(__name__)

OTP_Logo_URL = "https://cdn.some.engineering/assets/fix-logos/fix-logo-512.png"


async def get_auth_url(
    request: Request, state: str, client: BaseOAuth2[Any], auth_backend: AuthenticationBackend[Any, Any]
) -> OAuthProviderAuthUrl:
    # as defined in oauth_router.py # noqa
    callback_url_name = f"oauth:{client.name}.{auth_backend.name}.callback"
    # where oauth should call us back
    callback_url = str(request.url_for(callback_url_name))
    # the link to start the authorization with the oauth provider
    auth_url = await client.get_authorization_url(callback_url, state)
    return OAuthProviderAuthUrl(name=client.name, authUrl=auth_url)


async def get_associate_url(
    request: Request,
    state: str,
    client: BaseOAuth2[Any],
) -> str:
    # as defined in oauth_router.py # noqa
    callback_url_name = f"oauth-associate:{client.name}.callback"
    # where oauth should call us back
    callback_url = str(request.url_for(callback_url_name))
    # the link to start the authorization with the oauth provider
    return await client.get_authorization_url(callback_url, state)


def auth_router(config: Config, google_client: GoogleOAuth2, github_client: GithubOauthClient) -> APIRouter:
    router = APIRouter()

    auth_backend = get_auth_backend(config)

    router.include_router(
        get_oauth_router(
            google_client,
            auth_backend,
            config.secret,
            is_verified_by_default=True,
            associate_by_email=True,
            state_token_ttl=config.oauth_state_token_ttl,
        ),
        prefix="/google",
        tags=["auth"],
        # oauth routes are not supposed to be called by the user agent, so we don't need to show them in the docs
        include_in_schema=False,
    )

    router.include_router(
        get_oauth_associate_router(
            oauth_client=google_client,
            authenticator=fastapi_users.authenticator,
            state_secret=config.secret,
            requires_verification=True,
        ),
        prefix="/google/associate",
        tags=["auth"],
        include_in_schema=False,
    )

    router.include_router(
        get_oauth_router(
            github_client,
            auth_backend,
            config.secret,
            is_verified_by_default=True,
            associate_by_email=True,
            state_token_ttl=config.oauth_state_token_ttl,
        ),
        prefix="/github",
        tags=["auth"],
        # oauth routes are not supposed to be called by the user agent, so we don't need to show them in the docs
        include_in_schema=False,
    )

    router.include_router(
        get_oauth_associate_router(
            oauth_client=github_client,
            authenticator=fastapi_users.authenticator,
            state_secret=config.secret,
            requires_verification=True,
        ),
        prefix="/github/associate",
        tags=["auth"],
        include_in_schema=False,
    )

    @router.post("/mfa/add")
    async def add_mfa(user: AuthenticatedUser, user_manager: UserManager = Depends(get_user_manager)) -> OTPConfig:
        if user.is_mfa_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="MFA already enabled",
            )
        # create a new one-time password
        user_secret = pyotp.random_base32()
        totp = pyotp.totp.TOTP(user_secret)
        # store the secret
        await user_manager.user_repository.update(user, {"otp_secret": user_secret, "is_mfa_active": False})
        # return the OTP Config
        return OTPConfig(uri=totp.provisioning_uri(name=user.email, issuer_name="Fix", image=OTP_Logo_URL))

    @router.post("/mfa/enable")
    async def enable_mfa(
        user: AuthenticatedUser, client_secret: str = Form(), user_manager: UserManager = Depends(get_user_manager)
    ) -> Response:
        if user.is_mfa_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="MFA already enabled",
            )
        if (secret := user.otp_secret) is None or not pyotp.TOTP(secret).verify(client_secret):
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail="MFA_NOT_PROVIDED_OR_INVALID",
            )
        await user_manager.user_repository.update(user, {"is_mfa_active": True})
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/mfa/disable")
    async def disable_mfa(
        user: AuthenticatedUser, client_secret: str = Form(), user_manager: UserManager = Depends(get_user_manager)
    ) -> Response:
        if user.is_mfa_active:
            if (secret := user.otp_secret) is not None and not pyotp.TOTP(secret).verify(client_secret):
                raise HTTPException(
                    status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                    detail="MFA_NOT_PROVIDED_OR_INVALID",
                )
            await user_manager.user_repository.update(user, {"is_mfa_active": False, "otp_secret": None})
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # TODO: remove jwt from path
    @router.post("/jwt/login", name=f"auth:{auth_backend.name}.login")
    async def login(
        request: Request,
        credentials: OAuth2PasswordRequestForm = Depends(),
        user_manager: UserManager = Depends(get_user_manager),
        strategy: FixJWTStrategy = Depends(auth_backend.get_strategy),
    ) -> Response:
        user = await user_manager.authenticate(credentials)

        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorCode.LOGIN_BAD_CREDENTIALS,
            )
        if not user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorCode.LOGIN_USER_NOT_VERIFIED,
            )
        if user.is_mfa_active:
            if (
                (otp_secret := user.otp_secret) is None
                or (client_secret := credentials.client_secret) is None
                or not pyotp.TOTP(otp_secret).verify(client_secret)
            ):
                raise HTTPException(
                    status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                    detail="MFA_NOT_PROVIDED_OR_INVALID",
                )
        response = await auth_backend.login(strategy, user)
        await user_manager.on_after_login(user, request, response)
        return response

    # TODO: remove jwt from path
    @router.post("/jwt/logout", name=f"auth:{auth_backend.name}.logout")
    async def logout(
        user_token: Tuple[Optional[User], Optional[str]] = Depends(
            fastapi_users.authenticator.current_user_token(optional=True, active=True, verified=True)
        ),
        strategy: Strategy[User, UserId] = Depends(auth_backend.get_strategy),
    ) -> Response:
        user, token = user_token
        if user is None or token is None:
            # no one to logout
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        return await auth_backend.logout(strategy, user, token)

    router.include_router(
        fastapi_users.get_register_router(user_schema=UserRead, user_create_schema=UserCreate),
        tags=["auth"],
    )

    router.include_router(
        fastapi_users.get_reset_password_router(),
        tags=["auth"],
    )

    router.include_router(
        fastapi_users.get_verify_router(UserRead),
        tags=["auth"],
    )

    @router.get("/oauth-providers", tags=["auth"])
    async def list_all_oauth_providers(request: Request, redirect_url: str = "/") -> List[OAuthProviderAuthUrl]:
        state_data: Dict[str, str] = {}
        state_data["redirect_url"] = redirect_url
        state = generate_state_token(state_data, config.secret, config.oauth_state_token_ttl)

        clients: List[BaseOAuth2[Any]] = [google_client, github_client]
        return [await get_auth_url(request, state, client, auth_backend) for client in clients]

    @router.delete("/oauth-accounts/{provider_id}", tags=["auth"])
    async def unlink_oauth_account(
        user: AuthenticatedUser, provider_id: UUID, user_manager: UserManagerDependency
    ) -> None:
        user_oauth_accounts = [acc.id for acc in user.oauth_accounts]
        if provider_id not in user_oauth_accounts:
            raise HTTPException(status_code=403, detail="Not allowed to unlink this provider")

        await user_manager.remove_oauth_account(provider_id)

    @router.get("/oauth-associate", tags=["auth"])
    async def list_oauth_associate_providers(
        request: Request, user: AuthenticatedUser, redirect_url: str = "/"
    ) -> List[OAuthProviderAssociateUrl]:
        state_data: Dict[str, str] = {}
        state_data["redirect_url"] = redirect_url
        state_data["sub"] = str(user.id)
        state = generate_state_token(state_data, config.secret, config.oauth_state_token_ttl)

        clients: Dict[str, BaseOAuth2[Any]] = {
            google_client.name: google_client,
            github_client.name: github_client,
        }

        associate_urls: List[OAuthProviderAssociateUrl] = []

        user_oauth_accounts_names = {acc.oauth_name for acc in user.oauth_accounts}

        # step 1: put already associated accounts
        for oauth_account in user.oauth_accounts:
            client = clients.get(oauth_account.oauth_name)
            if not client:
                log.warning(f"Unknown oauth provider {oauth_account.oauth_name}")
                continue
            auth_url = await get_associate_url(request, state, client)
            associate_urls.append(
                OAuthProviderAssociateUrl(
                    name=oauth_account.oauth_name,
                    associated=True,
                    account_email=oauth_account.username or oauth_account.account_email,
                    account_id=oauth_account.id,
                    authUrl=auth_url,
                )
            )

        # step 2: add not yet associated accounts
        for client_name, client in clients.items():
            # skip already associated accounts
            if client_name in user_oauth_accounts_names:
                continue
            auth_url = await get_associate_url(request, state, client)
            associate_urls.append(
                OAuthProviderAssociateUrl(
                    name=client_name,
                    associated=False,
                    account_email=None,
                    account_id=None,
                    authUrl=auth_url,
                )
            )

        return associate_urls

    return router
