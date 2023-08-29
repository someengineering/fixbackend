from typing import Annotated, Dict
from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse
from fastapi.security.http import HTTPBearer
from fastapi_users.router.oauth import generate_state_token

from fixbackend.db import User
from fixbackend.schemas import UserRead, UserUpdate
from fixbackend.users import (
    SECRET,
    auth_backend,
    oauth_redirect_backend,
    current_active_user,
    fastapi_users,
    google_oauth_client,
    get_jwt_strategy
)

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
    fastapi_users.get_oauth_router(google_oauth_client, oauth_redirect_backend, SECRET, is_verified_by_default=True, associate_by_email=True),
    prefix="/auth/google",
    tags=["auth"],
)


@app.post("/auth/jwt/refresh", tags=["auth"])
async def refresh_jwt(context: UserContext):
    """Refresh the JWT token if still logged in."""
    return await auth_backend.login(get_jwt_strategy(), context.user)


@app.get("/login", response_class=HTMLResponse)
async def home():
    state_data: Dict[str, str] = {}
    state = generate_state_token(state_data, SECRET)
    auth_url = await google_oauth_client.get_authorization_url("http://127.0.0.1:8000/auth/google/callback", state)
    html_content = f"""
    <html>
        <head>
            <title>FIX Backend</title>
        </head>
        <body>
            <h1>Welcome to FIX Backend!</h1>

            <a href="{auth_url}">Login via Google</a>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)


@app.get("/app", response_class=HTMLResponse)
async def single_page_app():
    state_data: Dict[str, str] = {}
    state = generate_state_token(state_data, SECRET)
    auth_url = await google_oauth_client.get_authorization_url("http://127.0.0.1:8000/auth/google/callback", state)
    html_content = f"""
    <html>
        <head>
            <title>FIX Single page app</title>
        </head>
        <body>
            <h1>Welcome to beginning of the FIX Single Page App!</h1>

            <p>Do you want to start building the SPA? Please have an auth cookie:</p> <code id="cookie"></code>;
            <script>
            document.getElementById("cookie").innerHTML=document.cookie; 
            </script>

        </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)



