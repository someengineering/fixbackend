"""add last_scan_repo

Revision ID: 4df8ea080f3e
Revises: 2cbb6dcf9d01
Create Date: 2023-10-19 16:21:19.099419+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4df8ea080f3e"
down_revision: Union[str, None] = "2cbb6dcf9d01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "last_scan_reposotory",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    # ### end Alembic commands ###
