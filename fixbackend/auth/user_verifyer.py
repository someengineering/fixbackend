from typing import Annotated
from abc import ABC, abstractmethod
from fastapi import Depends
from fixbackend.auth.models import User


class UserVerifyer(ABC):
    @abstractmethod
    async def verify(self, user: User, token: str) -> None:
        pass


class ConsoleUserVerifyer(UserVerifyer):
    async def verify(self, user: User, token: str) -> None:
        print(f"Verification requested for user {user.id}. Verification token: {token}")


def get_user_verifyer() -> UserVerifyer:
    return ConsoleUserVerifyer()


UserVerifyerDependency = Annotated[UserVerifyer, Depends(get_user_verifyer)]
