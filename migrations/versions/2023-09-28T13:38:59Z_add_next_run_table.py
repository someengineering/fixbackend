"""add next_run table

Revision ID: e3ddf05cd115
Revises: 9f0f5d8ec3d5
Create Date: 2023-09-28 13:38:59.635966+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from fastapi_users_db_sqlalchemy import GUID

# revision identifiers, used by Alembic.
revision: str = "e3ddf05cd115"
down_revision: Union[str, None] = "9f0f5d8ec3d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "next_run",
        sa.Column("cloud_account_id", GUID(), nullable=False),
        sa.Column("at", sa.DATETIME(), nullable=False),
        sa.PrimaryKeyConstraint("cloud_account_id"),
    )
    op.create_index("idx_at", "next_run", ["at"], unique=False)
    # ### end Alembic commands ###
