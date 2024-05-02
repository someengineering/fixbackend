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
from typing import List, Optional

from fastapi import Response, Body
from fastapi.routing import APIRouter
from starlette.responses import JSONResponse

from fixbackend.auth.api_token_service import ApiTokenService
from fixbackend.auth.depedencies import AuthenticatedUser
from fixbackend.auth.schemas import ApiTokenData, ApiTokenDetails, ApiTokenDelete, ApiTokenCreate
from fixbackend.dependencies import FixDependencies, ServiceNames


def api_token_router(deps: FixDependencies) -> APIRouter:
    router = APIRouter()
    api_token_service = deps.service(ServiceNames.api_token_service, ApiTokenService)

    @router.post("/access", summary="Get JWT access token from API Token")
    async def access(data: ApiTokenData = Body(...)) -> Response:
        jwt = await api_token_service.login(data.token)
        return JSONResponse(content={"access_token": jwt})

    @router.post("/", summary="Create a new API Token")
    async def create_token(user: AuthenticatedUser, data: ApiTokenCreate = Body(...)) -> ApiTokenData:
        _, token = await api_token_service.create_token(user, data.name, data.permission, data.workspace_id)
        return ApiTokenData(token=token)

    @router.delete("/", summary="Delete API Token")
    async def delete_token(user: AuthenticatedUser, data: ApiTokenDelete) -> Response:
        await api_token_service.delete_token(user, api_token=data.token, api_token_name=data.name)
        return Response(status_code=204)

    @router.post("/info", summary="Get API Token Info")
    async def token_info(user: AuthenticatedUser, data: ApiTokenDelete) -> Optional[ApiTokenDetails]:
        info = await api_token_service.token_info(user, api_token=data.token, api_token_name=data.name)
        return ApiTokenDetails.from_token(info) if info else None

    @router.get("/", summary="List all API Tokens of the current user.")
    async def list_token(user: AuthenticatedUser) -> List[ApiTokenDetails]:
        return [ApiTokenDetails.from_token(a) for a in await api_token_service.list_tokens(user)]

    return router
