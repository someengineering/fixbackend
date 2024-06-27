"""store free tier ack

Revision ID: ca3c66dee1a1
Revises: 0c53039b3e7d
Create Date: 2024-06-27 14:05:21.961407+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from fixbackend.sqlalechemy_extensions import UTCDateTime


# revision identifiers, used by Alembic.
revision: str = "ca3c66dee1a1"
down_revision: Union[str, None] = "0c53039b3e7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("organization", sa.Column("move_to_free_acknowledged_at", UTCDateTime(timezone=True), nullable=True))
