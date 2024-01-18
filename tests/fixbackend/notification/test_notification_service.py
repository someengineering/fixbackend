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


import pytest
from fixbackend.notification.messages import SecurityScanFinished

from fixbackend.workspaces.models import Workspace
from fixbackend.workspaces.repository import WorkspaceRepository
from fixbackend.notification.service import NotificationService
from tests.fixbackend.conftest import InMemoryEmailSender
from fixbackend.auth.user_repository import UserRepository


@pytest.mark.asyncio
async def test_sent_to_workspace(
    notification_service: NotificationService,
    workspace: Workspace,
    workspace_repository: WorkspaceRepository,
    user_repository: UserRepository,
    email_sender: InMemoryEmailSender,
) -> None:
    for id in range(100):
        user_dict = {
            "email": f"user-{id}@bar.com",
            "hashed_password": "notreallyhashed",
            "is_verified": True,
        }
        user = await user_repository.create(user_dict)
        await workspace_repository.add_to_workspace(workspace.id, user.id)

    await notification_service.send_message_to_workspace(workspace_id=workspace.id, message=SecurityScanFinished())

    # emails must be sent in batches of no more than 50
    assert len(email_sender.call_args) == 3
    assert len(email_sender.call_args[0].to) == 50
    assert len(email_sender.call_args[1].to) == 50
    assert len(email_sender.call_args[2].to) == 1


@pytest.mark.asyncio
async def test_sent_email(
    notification_service: NotificationService,
    email_sender: InMemoryEmailSender,
) -> None:
    await notification_service.send_email(to="1", subject="2", text="3", html="4")

    assert len(email_sender.call_args) == 1
    args = email_sender.call_args[0]
    assert args.to == ["1"]
    assert args.subject == "2"
    assert args.text == "3"
    assert args.html == "4"


@pytest.mark.asyncio
async def test_sent_message(
    notification_service: NotificationService,
    email_sender: InMemoryEmailSender,
) -> None:
    message = SecurityScanFinished()
    await notification_service.send_message(to="1", message=message)

    assert len(email_sender.call_args) == 1
    args = email_sender.call_args[0]
    assert args.to == ["1"]
    assert args.subject == message.subject()
    assert args.text == message.text()
    assert args.html == message.html()
