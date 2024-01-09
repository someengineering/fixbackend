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
import hashlib
import os
import signal
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional, Callable, TypeVar, Iterable, Dict, List, Any
from uuid import UUID

from fixcloudutils.util import utc

AnyT = TypeVar("AnyT")
AnyR = TypeVar("AnyR")


def uid() -> UUID:
    return uuid.uuid4()


def kill_running_process() -> None:
    os.kill(os.getpid(), signal.SIGINT)


def group_by(iterable: Iterable[AnyT], f: Callable[[AnyT], AnyR]) -> Dict[AnyR, List[AnyT]]:
    v = defaultdict(list)
    for item in iterable:
        key = f(item)
        v[key].append(item)
    return v


def md5(s: Any) -> str:
    md5_hash = hashlib.md5()
    md5_hash.update(str(s).encode("utf-8"))
    return md5_hash.hexdigest()


def start_of_next_month(current_time: Optional[datetime] = None, hour: int = 0) -> datetime:
    now = current_time or utc()
    return (
        datetime(now.year + 1, 1, 1, hour=hour, tzinfo=timezone.utc)
        if now.month == 12
        else datetime(now.year, now.month + 1, 1, hour=hour, tzinfo=timezone.utc)
    )
