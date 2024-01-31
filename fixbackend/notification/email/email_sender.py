#  Copyright (c) 2023-2024. Some Engineering
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
from typing import List, Optional
import boto3
from fixbackend.config import Config


class EmailSender(ABC):
    @abstractmethod
    async def send_email(
        self,
        *,
        to: List[str],
        subject: str,
        text: str,
        html: Optional[str],
    ) -> None:
        """Send an email to the given address."""
        raise NotImplementedError()


class Boto3EmailSender(EmailSender):
    def __init__(self, config: Config) -> None:
        self.config = config
        self.ses = boto3.client(
            "ses",
            config.aws_region,
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
        )

    async def send_email(
        self,
        *,
        to: List[str],
        subject: str,
        text: str,
        html: Optional[str],
    ) -> None:  # pragma: no cover
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
                    "ToAddresses": to,
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


class ConsoleEmailSender(EmailSender):
    async def send_email(
        self,
        to: List[str],
        subject: str,
        text: str,
        html: Optional[str],
    ) -> None:  # pragma: no cover
        print(f"Sending emails to {to} with subject {subject}")
        print(f"text: {text}")
        if html:
            print(f"html: {html}")


def email_sender_from_config(config: Config) -> EmailSender:
    return (
        Boto3EmailSender(config) if config.aws_access_key_id and config.aws_secret_access_key else ConsoleEmailSender()
    )
