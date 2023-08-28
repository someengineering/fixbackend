from typing import Annotated
from fastapi import Depends, FastAPI

from fixbackend.db import User, create_db_and_tables
from fixbackend.schemas import UserRead, UserUpdate
from fixbackend.users import (
    SECRET,
    auth_backend,
    current_active_user,
    fastapi_users,
    google_oauth_client,
    get_jwt_strategy
)
from fastapi.security.http import HTTPBearer

app = FastAPI()

# a workaround for swagger to allow injecting JWT tokens
bearer_header = HTTPBearer()

class CurrentActiveUserDependencies:
    def __init__(
            self, 
            swagger_auth_workaround: Annotated[str, Depends(bearer_header)], # workaround to force swagger eat JWT tokens
            user: Annotated[User, Depends(current_active_user)], 
        ) -> None:
        self.user = user

UserContext = Annotated[CurrentActiveUserDependencies, Depends()]

@app.get("/hello")
async def hello(context: UserContext):
    """
    Replies back with "Hello <user_email>!" if the user is authenticated.
    """
    return {"message": f"Hello {context.user.email}!"}


app.include_router(
    fastapi_users.get_oauth_router(google_oauth_client, auth_backend, SECRET, is_verified_by_default=True, associate_by_email=True),
    prefix="/auth/google",
    tags=["auth"],
)


@app.post("/auth/jwt/refresh", tags=["auth"])
async def refresh_jwt(context: UserContext):
    """Refresh the JWT token if still logged in."""
    return await auth_backend.login(get_jwt_strategy(), context.user)


@app.on_event("startup")
async def on_startup():
    # Not needed if you setup a migration system like Alembic
    await create_db_and_tables()

