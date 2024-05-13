"""add workspace_id to subscription table

Revision ID: cd7a04e7394c
Revises: 855bc1b7b7d1
Create Date: 2024-05-07 20:08:13.021957+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from fastapi_users_db_sqlalchemy.generics import GUID

# revision identifiers, used by Alembic.
revision: str = "cd7a04e7394c"
down_revision: Union[str, None] = "57828ccdb2d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("stripe_workspace_id", GUID, nullable=True))
    op.create_index(
        op.f("ix_subscriptions_stripe_workspace_id"), "subscriptions", ["stripe_workspace_id"], unique=False
    )


def downgrade() -> None:
    pass
