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
import uuid
from datetime import datetime, timezone

import pytest

from fixbackend.ids import SecurityTier, WorkspaceId, CloudAccountId
from fixbackend.metering import MeteringRecord, MeteringSummary
from fixbackend.metering.metering_repository import MeteringRepository


def create_metering_record(workspace_id: WorkspaceId, account_id: str, security_tier: SecurityTier) -> MeteringRecord:
    ts = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return MeteringRecord(
        id=uuid.uuid1(),
        workspace_id=workspace_id,
        timestamp=ts,
        job_id="123e4567-e89b-12d3-a456-426614174000",
        task_id="123e4567-e89b-12d3-a456-426614174000",
        cloud="aws",
        account_id=CloudAccountId(account_id),
        account_name="test",
        nr_of_resources_collected=424242,
        nr_of_error_messages=1,
        started_at=ts,
        duration=1,
        security_tier=security_tier,
    )


@pytest.fixture
def metering_record() -> MeteringRecord:
    return create_metering_record(WorkspaceId(uuid.uuid1()), "123456789012", SecurityTier.HighSecurity)


@pytest.mark.asyncio
async def test_create_load(metering_repository: MeteringRepository, metering_record: MeteringRecord) -> None:
    # make sure there are no entries for the tenant
    ws_id = metering_record.workspace_id
    assert [e async for e in metering_repository.list(ws_id)] == []
    # create the entry
    await metering_repository.add([metering_record])
    assert [e async for e in metering_repository.list(ws_id)] == [metering_record]
    # collect summary
    assert [e async for e in metering_repository.collect_summary(ws_id)] == [
        MeteringSummary("123456789012", "test", 1, SecurityTier.HighSecurity)
    ]

    more = metering_record.nr_of_resources_collected + 1
    assert [e async for e in metering_repository.collect_summary(ws_id, min_resources_collected=more)] == []
