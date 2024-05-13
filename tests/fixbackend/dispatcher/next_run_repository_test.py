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
from datetime import timedelta, datetime
from typing import Optional

import pytest
from fixcloudutils.util import utc
from pytest import approx

from fixbackend.config import ProductTierSettings
from fixbackend.dispatcher.next_run_repository import NextRunRepository
from fixbackend.ids import WorkspaceId, ProductTier


@pytest.mark.asyncio
async def test_create(next_run_repository: NextRunRepository) -> None:
    cid = WorkspaceId(uuid.uuid1())
    now = utc()
    now_minus_1 = now - timedelta(minutes=1)
    await next_run_repository.create(cid, now_minus_1)
    # no entries that are older than 1 hour
    entries = [entry async for entry in next_run_repository.older_than(now - timedelta(hours=1))]
    assert len(entries) == 0
    # one entry that is older than now
    assert [entry[0] async for entry in next_run_repository.older_than(now)] == [cid]
    # update the entry to run in 1 hour
    await next_run_repository.update_next_run_at(cid, now + timedelta(hours=1))
    assert [entry[0] async for entry in next_run_repository.older_than(now)] == []
    assert [entry[0] async for entry in next_run_repository.older_than(now + timedelta(hours=2))] == [cid]
    # delete the entry
    await next_run_repository.delete(cid)
    assert [entry async for entry in next_run_repository.older_than(now + timedelta(days=365))] == []


@pytest.mark.asyncio
async def test_compute_next_run(next_run_repository: NextRunRepository) -> None:

    for product_tier in ProductTier:
        settings = ProductTierSettings[product_tier]
        delta = settings.scan_interval

        async def assert_next_is(last_run: Optional[datetime], expected: datetime) -> None:
            nr = next_run_repository.next_run_for(product_tier, last_run)
            assert nr.timestamp() == approx(expected.timestamp(), abs=2)

        now = utc()
        await assert_next_is(None, now + delta)
        await assert_next_is(now, now + delta)
        await assert_next_is(now + timedelta(seconds=10), now + delta + timedelta(seconds=10))
        await assert_next_is(now - timedelta(seconds=10), now + delta - timedelta(seconds=10))
        await assert_next_is(now + 3 * delta, now + 4 * delta)
        await assert_next_is(now - 3 * delta, now + delta)
        await assert_next_is(now - 123 * delta, now + delta)
