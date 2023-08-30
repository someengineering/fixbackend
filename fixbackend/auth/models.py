from typing import List

from fastapi_users.db import (
    SQLAlchemyBaseOAuthAccountTableUUID,
    SQLAlchemyBaseUserTableUUID,
)
from sqlalchemy.orm import Mapped, relationship
from fixbackend.models import Base

class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    pass

class User(SQLAlchemyBaseUserTableUUID, Base):
    oauth_accounts: Mapped[List[OAuthAccount]] = relationship(
        "OAuthAccount", lazy="joined"
    )
