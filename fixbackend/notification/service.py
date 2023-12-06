import asyncio
from abc import ABC
from typing import Annotated, Optional

import boto3
from fastapi import Depends

from fixbackend.config import Config, ConfigDependency


class NotificationService(ABC):
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


class ConsoleNotificationService(NotificationService):
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


class NotificationServiceImpl(NotificationService):
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


def get_notification_service(config: ConfigDependency) -> NotificationService:
    if config.aws_access_key_id and config.aws_secret_access_key:
        return NotificationServiceImpl(config)
    return ConsoleNotificationService()


NotificationServiceDependency = Annotated[NotificationService, Depends(get_notification_service)]
