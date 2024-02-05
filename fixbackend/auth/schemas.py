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

import uuid
from pydantic import BaseModel, Field
from fastapi_users import schemas


class UserRead(schemas.BaseUser[uuid.UUID]):
    pass


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    pass


class OAuthProviderAuthUrl(BaseModel):
    name: str = Field(description="Name of the OAuth provider")
    authUrl: str = Field(description="URL to initiate auth flow")


class OAuthProviderAssociateUrl(BaseModel):
    name: str = Field(description="Name of the OAuth provider")
    associated: bool = Field(description="Whether the user is already associated with this provider")
    account_id: uuid.UUID | None = Field(description="ID of the OAuth account, if associated")
    account_email: str | None = Field(description="Email of the user if already associated")
    authUrl: str = Field(description="URL to initiate association flow")
