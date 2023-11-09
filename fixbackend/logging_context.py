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
from typing import Dict, Any

from fixbackend.ids import WorkspaceId, FixCloudAccountId, CloudAccountId, UserId

context_var: ContextVar[Dict[str, str]] = ContextVar("logging_context", default={})


def set_context(key: str, value: Any) -> None:
    context = dict(context_var.get())
    context[key] = str(value)
    context_var.set(context)


def set_workspace_id(workspace_id: str | WorkspaceId) -> None:
    set_context("workspace_id", workspace_id)


def set_user_id(user_id: str | UserId) -> None:
    set_context("user_id", user_id)


def set_fix_cloud_account_id(fix_cloud_account_id: str | FixCloudAccountId) -> None:
    set_context("fix_cloud_account_id", fix_cloud_account_id)


def set_cloud_account_id(cloud_account_id: str | CloudAccountId) -> None:
    set_context("cloud_account_id", cloud_account_id)


def get_logging_context() -> Dict[str, str]:
    return context_var.get()
