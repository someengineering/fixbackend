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
from fastapi import Depends

from fixbackend.config import Config, ConfigDependency


class EmailService(ABC):
    @abstractmethod
    async def send_email(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        html: Optional[str],
    ) -> None:
        """Send an email to the given address."""
        raise NotImplementedError()


class ConsoleEmailService(EmailService):
    async def send_email(
        self,
        to: str,
        subject: str,
        text: str,
        html: Optional[str],
    ) -> None:
        print(f"Sending email to {to} with subject {subject}")
        print(f"text: {text}")
        if html:
            print(f"html: {html}")


class EmailServiceImpl(EmailService):
    def __init__(self, config: Config) -> None:
        self.ses = boto3.client(
            "ses",
            config.aws_region,
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
        )

    async def send_email(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        html: Optional[str],
    ) -> None:
        def send_email() -> None:
            body_section = {
                "Text": {
                    "Charset": "UTF-8",
                    "Data": text,
                },
            }
            if html:
                body_section["Html"] = {
                    "Charset": "UTF-8",
                    "Data": html,
                }

            self.ses.send_email(
                Destination={
                    "ToAddresses": [
                        to,
                    ],
                },
                Message={
                    "Body": body_section,
                    "Subject": {
                        "Charset": "UTF-8",
                        "Data": subject,
                    },
                },
                Source="noreply@fix.tt",
            )

        await asyncio.to_thread(send_email)


def get_email_service(config: ConfigDependency) -> EmailService:
    if config.aws_access_key_id and config.aws_secret_access_key:
        return EmailServiceImpl(config)
    return ConsoleEmailService()


EmailServiceDependency = Annotated[EmailService, Depends(get_email_service)]
