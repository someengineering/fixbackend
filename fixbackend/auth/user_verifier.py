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

import asyncio
from abc import ABC, abstractmethod
from typing import Annotated, Optional

import boto3
from fastapi import Depends, Request

from fixbackend.auth.models import User
from fixbackend.config import Config, ConfigDependency


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


class ConsoleUserVerifier(UserVerifier):
    async def verify(self, user: User, token: str, request: Optional[Request]) -> None:
        assert request

        email_body = self.plaintext_email_content(request, token)

        print(email_body)


class EMailUserVerifier(UserVerifier):
    def __init__(self, config: Config) -> None:
        self.client = boto3.client(
            "ses",
            config.aws_region,
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
        )

    async def verify(self, user: User, token: str, request: Optional[Request]) -> None:
        destination = user.email
        assert request

        def send_email(destination: str, token: str) -> None:
            body_text = self.plaintext_email_content(request, token)

            self.client.send_email(
                Destination={
                    "ToAddresses": [
                        destination,
                    ],
                },
                Message={
                    "Body": {
                        "Text": {
                            "Charset": "UTF-8",
                            "Data": body_text,
                        },
                    },
                    "Subject": {
                        "Charset": "UTF-8",
                        "Data": "FIX: verify your e-mail address",
                    },
                },
                Source="noreply@fix.tt",
            )

        await asyncio.to_thread(lambda: send_email(destination, token))


def get_user_verifier(config: ConfigDependency) -> UserVerifier:
    if config.aws_access_key_id and config.aws_secret_access_key:
        return EMailUserVerifier(config)
    return ConsoleUserVerifier()


UserVerifierDependency = Annotated[UserVerifier, Depends(get_user_verifier)]
