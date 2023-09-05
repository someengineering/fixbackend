from typing import Any

from fastapi_users.authentication import JWTStrategy, AuthenticationBackend, BearerTransport


from fixbackend.config import get_config


bearer_transport = BearerTransport(
    tokenUrl=""
)  # tokenUrl is only needed for swagger and non-social login, it is no needed here.


def get_jwt_strategy() -> JWTStrategy[Any, Any]:
    return JWTStrategy(secret=get_config().secret, lifetime_seconds=3600)


# for all other authenticatino tasks
jwt_auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)
