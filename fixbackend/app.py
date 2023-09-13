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
