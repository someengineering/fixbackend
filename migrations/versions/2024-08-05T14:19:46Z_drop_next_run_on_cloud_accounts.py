"""drop next_run on cloud accounts

Revision ID: 8ba415cb19e1
Revises: dbe8f626f045
Create Date: 2024-08-05 14:19:46.108163+00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8ba415cb19e1"
down_revision: Union[str, None] = "dbe8f626f045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("cloud_account", "next_scan")


def downgrade() -> None:
    pass
