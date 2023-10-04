"""add json kv store

Revision ID: 9b482c179740
Revises: 3b44ef1c41a0
Create Date: 2023-10-02 12:17:40.712823+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9b482c179740"
down_revision: Union[str, None] = "3b44ef1c41a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "key_value_json",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
