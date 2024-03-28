#  Copyright (c) 2024. Some Engineering
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

from typing import Sequence, Union

import fastapi_users_db_sqlalchemy
from alembic import op
import sqlalchemy as sa
from fastapi_users_db_sqlalchemy import GUID

from fixbackend.sqlalechemy_extensions import UTCDateTime

revision: str = "4345cdee91d1"
down_revision: Union[str, None] = "37c97e80bf4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("created_at", UTCDateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.add_column(
        "user",
        sa.Column("updated_at", UTCDateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "scheduled_email",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("after", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "scheduled_email_sent",
        sa.Column("id", fastapi_users_db_sqlalchemy.generics.GUID(), nullable=False),
        sa.Column("user_id", fastapi_users_db_sqlalchemy.generics.GUID(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("at", UTCDateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    oneday = 24 * 3600
    op.execute( f"INSERT INTO scheduled_email (id, kind, after) VALUES ('EC177BEF-E1F5-4660-8843-D8110DB8B4D1', 'day1', {oneday})" )  # fmt: skip # noqa
    op.execute( f"INSERT INTO scheduled_email (id, kind, after) VALUES ('EC177BEF-E1F5-4660-8843-D8110DB8B4D2', 'day2', {2*oneday})" )  # fmt: skip # noqa
    op.execute( f"INSERT INTO scheduled_email (id, kind, after) VALUES ('EC177BEF-E1F5-4660-8843-D8110DB8B4D3', 'day3', {3*oneday})" )  # fmt: skip # noqa
    op.execute( f"INSERT INTO scheduled_email (id, kind, after) VALUES ('EC177BEF-E1F5-4660-8843-D8110DB8B4D4', 'day4', {4*oneday})" )  # fmt: skip # noqa
    op.execute( f"INSERT INTO scheduled_email (id, kind, after) VALUES ('EC177BEF-E1F5-4660-8843-D8110DB8B4D5', 'day5', {5*oneday})" )  # fmt: skip # noqa
