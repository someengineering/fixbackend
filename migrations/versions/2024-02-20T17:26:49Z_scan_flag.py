"""scan flag

Revision ID: 4f583cb5ec57
Revises: 6a28d961d926
Create Date: 2024-02-20 17:26:49.983252+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

# revision identifiers, used by Alembic.
revision: str = "4f583cb5ec57"
down_revision: Union[str, None] = "6a28d961d926"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    try:
        op.add_column("cloud_account", sa.Column("scan", sa.Boolean(), nullable=False, default=False))
    except OperationalError:
        pass  # column already exists
    # all existing configured and enabled accounts should be scanned
    op.execute("UPDATE cloud_account SET scan = true WHERE is_configured = true and enabled = true and scan is null")
    # everything else should not be scanned
    op.execute("UPDATE cloud_account SET scan = false WHERE scan is null")
