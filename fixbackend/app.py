from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from fixbackend.auth.router import auth_router, login_page_router
from fixbackend.organizations.router import router as organizations_router

app = FastAPI()


app.include_router(
    auth_router,
    prefix="/api/auth",
    tags=["auth"],
)
app.include_router(
    organizations_router,
    prefix="/api/organizations",
    tags=["organizations"],
)

app.include_router(login_page_router, tags=["returns HTML"])


app.mount("/", StaticFiles(directory="fixbackend/static", html=True), name="static")
