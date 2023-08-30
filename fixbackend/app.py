from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from fixbackend.auth.router import auth_router
from fixbackend.auth.dependencies import UserContext

app = FastAPI()

@app.get("/hello")
async def hello(context: UserContext):
    """
    Replies back with "Hello <user_email>!" if the user is authenticated.
    """
    return {"message": f"Hello {context.user.email}!"}


app.include_router(
    auth_router,
    tags=["auth"],
)

@app.get("/app", response_class=HTMLResponse)
async def single_page_app():
    html_content = f"""
    <!DOCTYPE html>
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



