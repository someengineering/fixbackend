from typing import Any, Dict

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response

from fixbackend.auth.router import auth_router, login_page_router
from fixbackend.organizations.router import router as organizations_router
from fixbackend.auth.dependencies import AuthenticatedUser

app = FastAPI()


@app.get("/hello")
async def hello(context: AuthenticatedUser) -> Dict[str, Any]:
    """
    Replies back with "Hello <user_email>!" if the user is authenticated.
    """
    return {"message": f"Hello {context.user.email}!"}


app.include_router(
    auth_router,
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    organizations_router,
    prefix="/organizations",
    tags=["organizations"],
)

app.include_router(login_page_router, tags=["returns HTML"])


@app.get("/app", response_class=HTMLResponse, tags=["returns HTML"])
async def single_page_app_entrypoint() -> Response:
    html_content = f"""
    <!DOCTYPE html>
    <html>
        <head>
            <title>FIX Single page app</title>
        </head>
        <body>
            <h1>Welcome to beginning of the FIX Single Page App!</h1>

            <p>Do you want to start building the SPA? Please have a session token:</p> <code id="cookie"></code>
            <script>
            document.getElementById("cookie").innerHTML=localStorage.getItem("fix-jwt"); 
            </script>

        </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)
