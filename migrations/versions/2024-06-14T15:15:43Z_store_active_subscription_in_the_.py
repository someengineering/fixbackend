"""store active subscription in the workspace

Revision ID: 0c53039b3e7d
Revises: 167047784340
Create Date: 2024-06-14 15:15:43.128906+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from fixbackend.sqlalechemy_extensions import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0c53039b3e7d"
down_revision: Union[str, None] = "167047784340"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("organization", sa.Column("highest_current_cycle_tier", sa.String(length=64), nullable=True))
    op.add_column("organization", sa.Column("current_cycle_ends_at", UTCDateTime(timezone=True), nullable=True))
