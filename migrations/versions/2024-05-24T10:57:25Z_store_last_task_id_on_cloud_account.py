"""store last task_id on cloud_account

Revision ID: f510b2e977db
Revises: 93656ab46b96
Create Date: 2024-05-24 10:57:25.688324+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f510b2e977db"
down_revision: Union[str, None] = "93656ab46b96"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cloud_account", sa.Column("last_task_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    pass
