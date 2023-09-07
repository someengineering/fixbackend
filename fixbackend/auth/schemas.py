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
