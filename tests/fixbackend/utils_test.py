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
from datetime import datetime, timezone


from fixbackend.utils import start_of_next_month, batch


def test_start_of_next_month() -> None:
    utc = timezone.utc
    assert start_of_next_month(datetime(2023, 1, 23), hour=12) == datetime(2023, 2, 1, 12, tzinfo=utc)
    assert start_of_next_month(datetime(2023, 2, 1)) == datetime(2023, 3, 1, tzinfo=utc)
    assert start_of_next_month(datetime(2023, 12, 24)) == datetime(2024, 1, 1, tzinfo=utc)


def test_batch() -> None:
    def check_size(by: int, batch_count: int) -> None:
        batches = list(batch(range(100), by))
        assert len(batches) == batch_count
        for items in batches[:-1]:
            assert len(items) == by
        assert len(batches[-1]) <= by

    check_size(10, 10)
    check_size(100, 1)
    check_size(1, 100)
    check_size(5, 20)
