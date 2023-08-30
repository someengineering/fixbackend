from typing import Annotated, Dict
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.security.http import HTTPBearer
from fastapi_users.router.oauth import generate_state_token

from fixbackend.db import User
from fixbackend.users import (
    auth_backend,
    oauth_redirect_backend,
    current_active_user,
    fastapi_users,
    google_oauth_client,
    get_jwt_strategy
)
from fixbackend.config import get_config

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
    fastapi_users.get_oauth_router(google_oauth_client, oauth_redirect_backend, get_config().secret, is_verified_by_default=True, associate_by_email=True),
    prefix="/auth/google",
    tags=["auth"],
    include_in_schema=False
)



@app.post("/auth/jwt/refresh", tags=["auth"])
async def refresh_jwt(context: UserContext):
    """Refresh the JWT token if still logged in."""
    return await auth_backend.login(get_jwt_strategy(), context.user)


@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    state_data: Dict[str, str] = {}
    state = generate_state_token(state_data, get_config().secret)
    # as defined in https://github.com/fastapi-users/fastapi-users/blob/ff9fae631cdae00ebc15f051e54728b3c8d11420/fastapi_users/router/oauth.py#L41
    callback_url_name = f"oauth:{google_oauth_client.name}.{oauth_redirect_backend.name}.callback"
    # where google should call us back
    callback_url = str(request.url_for(callback_url_name))
    # the link to start the authorization with google
    auth_url = await google_oauth_client.get_authorization_url(callback_url, state)
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
    html_content = f"""
    <html>
        <head>
            <title>FIX Single page app</title>
        </head>
        <body>
            <h1>Welcome to beginning of the FIX Single Page App!</h1>

            <p>Do you want to start building the SPA? Please have a session token:</p> <code id="cookie"></code>;
            <script>
            document.getElementById("cookie").innerHTML=localStorage.getItem("fix-jwt"); 
            </script>

        </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)



