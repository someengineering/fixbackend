import uuid
from fastapi_users import FastAPIUsers

from fixbackend.auth.models import User
from fixbackend.auth.user_manager import get_user_manager
from fixbackend.auth.jwt import jwt_auth_backend


fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [jwt_auth_backend])

