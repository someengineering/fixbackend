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
