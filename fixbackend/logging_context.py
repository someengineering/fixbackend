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

from contextvars import ContextVar
from fixbackend.ids import WorkspaceId, UserId, CloudAccountId, FixCloudAccountId
from typing import Dict, Optional


workspace_id_var: ContextVar[Optional[WorkspaceId]] = ContextVar("workspace_id", default=None)
user_id_var: ContextVar[Optional[UserId]] = ContextVar("user_id", default=None)
fix_cloud_account_id_var: ContextVar[Optional[FixCloudAccountId]] = ContextVar("fix_cloud_account_id", default=None)
cloud_account_id_var: ContextVar[Optional[CloudAccountId]] = ContextVar("cloud_account_id", default=None)


def set_workspace_id(workspace_id: WorkspaceId) -> None:
    workspace_id_var.set(workspace_id)


def set_user_id(user_id: UserId) -> None:
    user_id_var.set(user_id)


def set_fix_cloud_account_id(fix_cloud_account_id: FixCloudAccountId) -> None:
    fix_cloud_account_id_var.set(fix_cloud_account_id)


def set_cloud_account_id(cloud_account_id: CloudAccountId) -> None:
    cloud_account_id_var.set(cloud_account_id)


def get_logging_context() -> Dict[str, str]:
    context = {}

    if workspace_id := workspace_id_var.get():
        context["workspace_id"] = str(workspace_id)

    if user_id := user_id_var.get():
        context["user_id"] = str(user_id)

    if fix_cloud_account_id := fix_cloud_account_id_var.get():
        context["fix_cloud_account_id"] = str(fix_cloud_account_id)

    if cloud_account_id := cloud_account_id_var.get():
        context["cloud_account_id"] = str(cloud_account_id)

    return context
