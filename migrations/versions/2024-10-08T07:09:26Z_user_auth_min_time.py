"""user:
Introduce auth_min_time column to user table.
Create Date: 2024-10-08 07:09:26.627447+00:00
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

from fixbackend.sqlalechemy_extensions import UTCDateTime

revision: str = "f5eaa189e1f2"
down_revision: Union[str, None] = "000dd4f966a4"


def upgrade() -> None:
    op.add_column("user", sa.Column("auth_min_time", UTCDateTime(timezone=True), nullable=True))
