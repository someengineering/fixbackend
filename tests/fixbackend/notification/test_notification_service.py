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

    await notification_service.send_email_to_workspace(
        workspace_id=workspace.id, subject="test", text="test", html=None
    )

    # emails must be sent in batches of no more than 50
    assert len(email_sender.call_args) == 3
    assert len(email_sender.call_args[0].to) == 50
    assert len(email_sender.call_args[1].to) == 50
    assert len(email_sender.call_args[2].to) == 1
