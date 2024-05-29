"""add an error field to gcp service account key table

Revision ID: 9cd3c7b42670
Revises: db7de870a6c7
Create Date: 2024-05-29 13:33:58.862323+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9cd3c7b42670"
down_revision: Union[str, None] = "db7de870a6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("gcp_service_account_key", sa.Column("error", sa.Text(), nullable=True))


def downgrade() -> None:
    pass
