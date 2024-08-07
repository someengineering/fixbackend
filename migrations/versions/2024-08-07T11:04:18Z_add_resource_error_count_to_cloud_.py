"""add resource error count to cloud account

Revision ID: 1e4ccaf4e087
Revises: 8ba415cb19e1
Create Date: 2024-08-07 11:04:18.404811+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from fixbackend.sqlalechemy_extensions import UTCDateTime


# revision identifiers, used by Alembic.
revision: str = "1e4ccaf4e087"
down_revision: Union[str, None] = "8ba415cb19e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cloud_account", sa.Column("last_scan_resources_errors", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "cloud_account", sa.Column("last_degraded_scan_started_at", UTCDateTime(timezone=True), nullable=True)
    )
