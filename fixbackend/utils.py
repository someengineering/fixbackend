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
import os
import signal
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fixcloudutils.util import utc


def uid() -> UUID:
    return uuid.uuid4()


def kill_running_process() -> None:
    os.kill(os.getpid(), signal.SIGINT)


def start_of_next_month(current_time: Optional[datetime] = None, hour: int = 0) -> datetime:
    now = current_time or utc()
    return (
        datetime(now.year + 1, 1, 1, hour=hour, tzinfo=timezone.utc)
        if now.month == 12
        else datetime(now.year, now.month + 1, 1, hour=hour, tzinfo=timezone.utc)
    )
