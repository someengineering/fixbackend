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
from datetime import datetime

from sqlalchemy import func, text, DefaultClause
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from fixbackend.sqlalechemy_extensions import UTCDateTime


class Base(DeclarativeBase):
    """
    Base class for SQLAlchemy model classes.

    All model classes should inherit from this class.
    """


class CreatedUpdatedMixin:
    """
    Mixin to always have created_at and updated_at columns in a model.
    """

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        server_default=func.now(),
        server_onupdate=DefaultClause(text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
    )
