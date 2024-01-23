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


from logging import getLogger
from typing import Annotated, Iterator, List, Optional

from fastapi import Depends

from fixbackend.config import ConfigDependency
from fixbackend.ids import WorkspaceId
from fixbackend.logging_context import set_workspace_id
from fixbackend.notification.messages import EmailMessage
from fixbackend.notification.email_sender import Boto3EmailSender, ConsoleEmailSender, EmailSender
from fixbackend.workspaces.repository import WorkspaceRepository, WorkspaceRepositoryDependency
from fixbackend.auth.user_repository import UserRepository, UserRepositoryDependency

log = getLogger(__name__)


class NotificationService:
    def __init__(
        self, workspace_repository: WorkspaceRepository, user_repository: UserRepository, email_sender: EmailSender
    ) -> None:
        self.workspace_repository = workspace_repository
        self.user_repository = user_repository
        self.email_sender = email_sender

    async def send_email(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        html: Optional[str],
    ) -> None:
        """Send an email to the given address."""
        await self.email_sender.send_email(to=[to], subject=subject, text=text, html=html)

    async def send_message(self, *, to: str, message: EmailMessage) -> None:
        await self.send_email(to=to, subject=message.subject(), text=message.text(), html=message.html())

    async def send_message_to_workspace(
        self,
        *,
        workspace_id: WorkspaceId,
        message: EmailMessage,
    ) -> None:
        set_workspace_id(workspace_id)
        workspace = await self.workspace_repository.get_workspace(workspace_id)
        if not workspace:
            log.error(f"Workspace {workspace_id} not found")
            return

        emails = [user.email for user in await self.user_repository.get_by_ids(workspace.all_users())]

        def batch(items: List[str], n: int = 50) -> Iterator[List[str]]:
            current_batch: List[str] = []
            for item in items:
                current_batch.append(item)
                if len(current_batch) == n:
                    yield current_batch
                    current_batch = []
            if current_batch:
                yield current_batch

        batches = list(batch(emails))

        for email_batch in batches:
            await self.email_sender.send_email(
                to=email_batch, subject=message.subject(), text=message.text(), html=message.html()
            )


def get_notification_service(
    config: ConfigDependency, workspace_repo: WorkspaceRepositoryDependency, user_repo: UserRepositoryDependency
) -> NotificationService:
    if config.aws_access_key_id and config.aws_secret_access_key:
        sender: EmailSender = Boto3EmailSender(config)
    else:
        sender = ConsoleEmailSender()
    return NotificationService(workspace_repo, user_repo, sender)


EmailServiceDependency = Annotated[NotificationService, Depends(get_notification_service)]
