"""user: last_login and activity

Revision ID: 000dd4f966a4
Revises: 2c3086217445
Create Date: 2024-10-07 09:24:49.803805+00:00

"""

from typing import Union

from alembic import op
import sqlalchemy as sa

from fixbackend.sqlalechemy_extensions import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "000dd4f966a4"
down_revision: Union[str, None] = "2c3086217445"


def upgrade() -> None:
    op.add_column("user", sa.Column("last_login", UTCDateTime(timezone=True), nullable=True))
    op.add_column("user", sa.Column("last_active", UTCDateTime(timezone=True), nullable=True))
