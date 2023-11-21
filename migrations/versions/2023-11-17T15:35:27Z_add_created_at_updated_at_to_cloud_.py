"""add created_at/updated_at to cloud_account

Revision ID: d294f6e4b5dc
Revises: b33942763df4
Create Date: 2023-11-17 15:35:27.215609+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from fixbackend.sqlalechemy_extensions import UTCDateTime


# revision identifiers, used by Alembic.
revision: str = "d294f6e4b5dc"
down_revision: Union[str, None] = "b33942763df4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        "cloud_account",
        sa.Column("created_at", UTCDateTime(timezone=True), nullable=False, server_default=sa.sql.func.now()),
    )
    op.add_column(
        "cloud_account",
        sa.Column("updated_at", UTCDateTime(timezone=True), nullable=False, server_default=sa.sql.func.now()),
    )
    op.add_column(
        "cloud_account",
        sa.Column("state_updated_at", UTCDateTime(timezone=True), nullable=False, server_default=sa.sql.func.now()),
    )
    op.add_column("cloud_account", sa.Column("version_id", sa.Integer(), nullable=False, server_default="0"))
    op.create_index(op.f("ix_cloud_account_state"), "cloud_account", ["state"], unique=False)
    # ### end Alembic commands ###