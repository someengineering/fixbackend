import os
import uuid
from typing import Optional, Annotated
import time

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    JWTStrategy,
    BearerTransport,
    CookieTransport
)
from httpx_oauth.clients.google import GoogleOAuth2
from fastapi_users.db import SQLAlchemyUserDatabase

from fixbackend.db import User, get_user_db
from fixbackend.auth.cookie_redirect_transport import CookieRedirectTransport

SECRET = "SECRET"

google_oauth_client = GoogleOAuth2(
    os.getenv("GOOGLE_OAUTH_CLIENT_ID", ""),
    os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", ""),
)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = SECRET
    verification_token_secret = SECRET




async def get_user_manager(user_db: Annotated[SQLAlchemyUserDatabase, Depends(get_user_db)]):
    yield UserManager(user_db)


bearer_transport = BearerTransport(tokenUrl="") # tokenUrl is only needed for swagger and non-social login, it is no needed here.

cookie_transport = CookieRedirectTransport(CookieTransport("fix-jwt", cookie_max_age=int(time.time())+10, cookie_httponly=False, cookie_path="/app"), redirect_path="/app")

def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=SECRET, lifetime_seconds=3600)

# only used for passing the jwt via a cookie after the sign in
oauth_redirect_backend = AuthenticationBackend(
    name="cookie-redirect",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy
)

# for all other authenticatino tasks
auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

current_active_user = fastapi_users.current_user(active=True)
