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
import uuid
from datetime import timedelta

import pytest
from fixcloudutils.util import utc

from fixbackend.dispatcher.next_run_repository import NextRunRepository
from fixbackend.ids import CloudAccountId


@pytest.mark.asyncio
async def test_create(next_run_repository: NextRunRepository) -> None:
    cid = CloudAccountId(uuid.uuid1())
    now = utc()
    now_minus_1 = now - timedelta(minutes=1)
    await next_run_repository.create(cid, now_minus_1)
    # no entries that are older than 1 hour
    entries = [entry async for entry in next_run_repository.older_than(now - timedelta(hours=1))]
    assert len(entries) == 0
    # one entry that is older than now
    assert [entry async for entry in next_run_repository.older_than(now)] == [cid]
    # update the entry to run in 1 hour
    await next_run_repository.update_next_run_at(cid, now + timedelta(hours=1))
    assert [entry async for entry in next_run_repository.older_than(now)] == []
    assert [entry async for entry in next_run_repository.older_than(now + timedelta(hours=2))] == [cid]
    # delete the entry
    await next_run_repository.delete(cid)
    assert [entry async for entry in next_run_repository.older_than(now + timedelta(days=365))] == []
