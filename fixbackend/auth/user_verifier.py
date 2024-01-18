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

from abc import ABC, abstractmethod
from typing import Annotated, Optional

from fastapi import Depends, Request

from fixbackend.auth.models import User
from fixbackend.notification.service import NotificationService, EmailServiceDependency
from fixbackend.notification.messages import VerifyEmail


class UserVerifier(ABC):
    def email_content(self, *, request: Request, user_email: str, token: str) -> VerifyEmail:
        # redirect is defined by the UI - use / as safe fallback
        redirect_url = request.query_params.get("redirectUrl", "/")
        verification_link = request.base_url
        verification_link = verification_link.replace(
            path="/auth/verify-email", query=f"token={token}&redirectUrl={redirect_url}"
        )

        return VerifyEmail(recipient=user_email, verification_link=str(verification_link))

    @abstractmethod
    async def verify(self, user: User, token: str, request: Optional[Request]) -> None:
        pass


class UserVerifierImpl(UserVerifier):
    def __init__(self, notification_service: NotificationService) -> None:
        self.notification_service = notification_service

    async def verify(self, user: User, token: str, request: Optional[Request]) -> None:
        assert request
        message = self.email_content(request=request, user_email=user.email, token=token)

        await self.notification_service.send_message(message=message, to=user.email)


def get_user_verifier(email_service: EmailServiceDependency) -> UserVerifier:
    return UserVerifierImpl(email_service)


UserVerifierDependency = Annotated[UserVerifier, Depends(get_user_verifier)]
