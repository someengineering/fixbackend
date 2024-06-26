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
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Dict
from urllib.parse import urlencode

import boto3
from fixbackend.config import Config
from fixbackend.fix_jwt import JwtService


class EmailSender(ABC):
    @abstractmethod
    async def send_email(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        html: Optional[str],
        unsubscribe: Optional[str] = None,  # kind of emails to unsubscribe from
        images: Optional[Dict[str, bytes]] = None,  # inline images to include in the email
    ) -> None:
        """Email the given address."""
        raise NotImplementedError()


EMAIL_UNSUBSCRIBE_AUDIENCE = "fix:unsubscribe"
EMAIL_FROM_ADDRESS = "support@fix.security"


class Boto3EmailSender(EmailSender):
    def __init__(self, config: Config, jwt_service: JwtService) -> None:
        self.jwt_service = jwt_service
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
        to: str,
        subject: str,
        text: str,
        html: Optional[str],
        unsubscribe: Optional[str] = None,
        images: Optional[Dict[str, bytes]] = None,
    ) -> None:  # pragma: no cover

        additional_headers = {}
        if kind := unsubscribe:
            params = dict(
                token=await self.jwt_service.encode({"sub": to, "kind": kind}, audience=[EMAIL_UNSUBSCRIBE_AUDIENCE]),
            )
            additional_headers["List-Unsubscribe"] = (
                f"<{self.config.service_base_url}/api/unsubscribe?{urlencode(params)}>"
            )
            additional_headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        def send_email() -> None:
            # Main message with 'mixed' for overall structure (if there are attachments)
            msg = MIMEMultipart("mixed")
            msg["Subject"] = subject
            msg["From"] = f"Fix Security <{EMAIL_FROM_ADDRESS}>"
            msg["To"] = to
            for key, value in additional_headers.items():
                msg.add_header(key, value)

            # 'Related' part for images and HTML
            related = MIMEMultipart("related")
            msg.attach(related)

            # 'Alternative' part for plain and HTML text versions
            alternative = MIMEMultipart("alternative")
            related.attach(alternative)

            if images:
                for name, content in images.items():
                    attachment = MIMEImage(content)
                    # define the image's ID as referenced in the HTML part
                    attachment.add_header("Content-ID", f"<{name}>")
                    # mark the content as inline (not attachment)
                    attachment.add_header("Content-Disposition", "inline", filename=name)
                    related.attach(attachment)

            plain_part = MIMEText(text, "plain")
            alternative.attach(plain_part)

            if html:
                html_part = MIMEText(html, "html")
                alternative.attach(html_part)

            self.ses.send_raw_email(
                Source=EMAIL_FROM_ADDRESS,
                Destinations=[to],
                RawMessage={"Data": msg.as_string().encode("utf-8")},
            )

        await asyncio.to_thread(send_email)


class ConsoleEmailSender(EmailSender):
    async def send_email(
        self,
        to: str,
        subject: str,
        text: str,
        html: Optional[str],
        unsubscribe: Optional[str] = None,
        images: Optional[Dict[str, bytes]] = None,
    ) -> None:  # pragma: no cover
        print(f"Sending emails to {to} with subject {subject}")
        print(f"text: {text}")
        if html:
            print(f"html: {html}")


def email_sender_from_config(config: Config, jwt_service: JwtService) -> EmailSender:
    return (
        Boto3EmailSender(config, jwt_service)
        if config.aws_access_key_id and config.aws_secret_access_key
        else ConsoleEmailSender()
    )
