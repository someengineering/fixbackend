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
from datetime import timedelta
from typing import Dict, Type

from fixcloudutils.types import Json
from fixcloudutils.util import utc

from fixbackend.domain_events.events import (
    UserRegistered,
    AwsAccountDiscovered,
    AwsAccountConfigured,
    AwsAccountDeleted,
    AwsAccountDegraded,
    TenantAccountsCollected,
    CloudAccountCollectInfo,
    WorkspaceCreated,
    Event,
)
from fixbackend.ids import TaskId, UserId, WorkspaceId, CloudAccountId, FixCloudAccountId
from fixbackend.utils import uid

user_id = UserId(uid())
cloud_account_id = CloudAccountId("123")
fix_cloud_account_id = FixCloudAccountId(uid())
workspace_id = WorkspaceId(uid())
now = utc()
task_id = TaskId("task_123")
collect_info = CloudAccountCollectInfo(cloud_account_id, 123, 123, now, task_id)
events = [
    UserRegistered(user_id, "test@example.com", workspace_id),
    AwsAccountDiscovered(fix_cloud_account_id, workspace_id, cloud_account_id),
    AwsAccountConfigured(fix_cloud_account_id, workspace_id, cloud_account_id),
    AwsAccountDeleted(user_id, fix_cloud_account_id, workspace_id, cloud_account_id),
    AwsAccountDegraded(fix_cloud_account_id, workspace_id, cloud_account_id, "some error"),
    TenantAccountsCollected(workspace_id, {fix_cloud_account_id: collect_info}, now + timedelta(hours=1)),
    WorkspaceCreated(workspace_id, user_id),
]

# CHANGING THE JSON STRUCTURE HERE MEANS BREAKING THE EVENT CONTRACT!
# LET'S TRY TO AVOID THAT UNLESS NECESSARY.
event_jsons: Dict[Type[Event], Json] = {
    UserRegistered: {
        "user_id": "ce63e341-ee3a-4300-bdf2-0df52486cccf",
        "email": "test@example.com",
        "tenant_id": "35dfca88-3028-4990-9d30-a269228d0b01",
    },
    AwsAccountDiscovered: {
        "cloud_account_id": "69dea3e9-bafe-4e80-9c9d-5a7e1b519767",
        "tenant_id": "35dfca88-3028-4990-9d30-a269228d0b01",
        "aws_account_id": "123",
    },
    AwsAccountConfigured: {
        "cloud_account_id": "69dea3e9-bafe-4e80-9c9d-5a7e1b519767",
        "tenant_id": "35dfca88-3028-4990-9d30-a269228d0b01",
        "aws_account_id": "123",
    },
    AwsAccountDeleted: {
        "cloud_account_id": "69dea3e9-bafe-4e80-9c9d-5a7e1b519767",
        "tenant_id": "35dfca88-3028-4990-9d30-a269228d0b01",
        "aws_account_id": "123",
    },
    AwsAccountDegraded: {
        "cloud_account_id": "69dea3e9-bafe-4e80-9c9d-5a7e1b519767",
        "tenant_id": "35dfca88-3028-4990-9d30-a269228d0b01",
        "aws_account_id": "123",
        "error": "some error",
    },
    TenantAccountsCollected: {
        "tenant_id": "35dfca88-3028-4990-9d30-a269228d0b01",
        "cloud_accounts": {
            "69dea3e9-bafe-4e80-9c9d-5a7e1b519767": {
                "account_id": "123",
                "scanned_resources": 123,
                "duration_seconds": 123,
                "started_at": "2023-11-28T08:19:02.393629+00:00",
                "task_id": "task_123",
            }
        },
        "next_run": "2023-11-28T09:19:02.393629+00:00",
    },
    WorkspaceCreated: {"workspace_id": "35dfca88-3028-4990-9d30-a269228d0b01"},
}


def test_json_roundtrip() -> None:
    for event in events:
        assert event == type(event).from_json(event.to_json())


def read_events() -> None:
    for clazz, example_json in event_jsons.items():
        assert clazz.from_json(example_json) is not None
