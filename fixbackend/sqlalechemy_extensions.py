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
from datetime import datetime, timezone
from typing import Optional, Any

import sqlalchemy as sa


class UTCDateTime(sa.types.TypeDecorator[sa.types.DateTime]):
    """
    Use this type to store datetime objects.
    It will make sure to use UTC timezone always.
    """

    impl = sa.types.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Optional[Any], dialect: sa.Dialect) -> Optional[Any]:
        if isinstance(value, datetime) and value.tzinfo is not timezone.utc:
            raise ValueError("Only datetime with timezone UTC are supported!")

        return value

    def process_result_value(self, value: Optional[Any], dialect: sa.Dialect) -> Optional[Any]:
        return value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) else value
