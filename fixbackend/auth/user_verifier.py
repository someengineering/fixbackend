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

import logging
from typing import Annotated, Optional

from fastapi import Depends, Request
from fastapi.datastructures import URL

from fixbackend.auth.models import User
from fixbackend.config import Config
from fixbackend.dependencies import FixDependency, ServiceNames
from fixbackend.notification.email.email_messages import PasswordReset, VerifyEmail
from fixbackend.notification.notification_service import NotificationService


log = logging.getLogger(__name__)


class AuthEmailSender:
    def __init__(self, notification_service: NotificationService, config: Config) -> None:
        self.notification_service = notification_service
        self.config = config

    async def send_verify_email(self, user: User, token: str, request: Optional[Request]) -> None:

        redirect_url = "/"
        verification_link = URL(self.config.service_base_url)
        if request:
            redirect_url = request.query_params.get("redirectUrl", "/")
            verification_link = request.base_url

        verification_link = verification_link.replace(
            path="/auth/verify-email", query=f"token={token}&redirectUrl={redirect_url}"
        )

        message = VerifyEmail(recipient=user.email, verification_link=str(verification_link))

        await self.notification_service.send_message(message=message, to=user.email)
        log.info(f"Sent account verification email to {user.email}")

    async def send_password_reset(self, user: User, token: str, request: Optional[Request]) -> None:
        assert request

        redirect_url = request.query_params.get("redirectUrl", "/")
        reset_link = request.base_url
        reset_link = reset_link.replace(path="/auth/reset-password", query=f"token={token}&redirectUrl={redirect_url}")

        message = PasswordReset(recipient=user.email, password_reset_link=str(reset_link))

        await self.notification_service.send_message(message=message, to=user.email)
        log.info(f"Sent password reset email to {user.email}")


def get_auth_email_sender(deps: FixDependency) -> AuthEmailSender:
    return deps.service(ServiceNames.auth_email_sender, AuthEmailSender)


AuthEmailSenderDependency = Annotated[AuthEmailSender, Depends(get_auth_email_sender)]
