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
from fixbackend.notification.service import NotificationService, NotificationServiceDependency


class UserVerifier(ABC):
    def plaintext_email_content(self, request: Request, token: str) -> str:
        # redirect is defined by the UI - use / as safe fallback
        redirect_url = request.query_params.get("redirectUrl", "/")
        verification_link = request.base_url
        verification_link = verification_link.replace(
            path="/auth/verify-email", query=f"token={token}&redirectUrl={redirect_url}"
        )

        body_text = f"Hello fellow FIX user, click this link to verify your email. {verification_link}"

        return body_text

    @abstractmethod
    async def verify(self, user: User, token: str, request: Optional[Request]) -> None:
        pass


class UserVerifierImpl(UserVerifier):
    def __init__(self, notification_service: NotificationService) -> None:
        self.notification_service = notification_service

    async def verify(self, user: User, token: str, request: Optional[Request]) -> None:
        assert request
        body_text = self.plaintext_email_content(request, token)

        await self.notification_service.send_email(
            to=user.email,
            subject="FIX: verify your e-mail address",
            text=body_text,
            html=None,
        )


def get_user_verifier(notification_service: NotificationServiceDependency) -> UserVerifier:
    return UserVerifierImpl(notification_service)


UserVerifierDependency = Annotated[UserVerifier, Depends(get_user_verifier)]
