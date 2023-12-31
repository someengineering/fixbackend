"""billing entity

Revision ID: d9be24f944dc
Revises: 69f29fc94a5c
Create Date: 2023-10-23 12:43:21.899358+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from fastapi_users_db_sqlalchemy import GUID
from sqlalchemy import DefaultClause, text

from fixbackend.sqlalechemy_extensions import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "d9be24f944dc"
down_revision: Union[str, None] = "69f29fc94a5c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "billing",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("workspace_id", GUID(), nullable=False),
        sa.Column("subscription_id", GUID(), nullable=False),
        sa.Column("tier", sa.String(64), nullable=False),
        sa.Column("nr_of_accounts_charged", sa.Integer(), nullable=False),
        sa.Column("period_start", UTCDateTime(timezone=True), nullable=False),
        sa.Column("period_end", UTCDateTime(timezone=True), nullable=False),
        sa.Column("reported", sa.Boolean(), nullable=False),
        sa.Column("created_at", UTCDateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "updated_at",
            UTCDateTime(timezone=True),
            server_default=sa.text("now()"),
            server_onupdate=DefaultClause(text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_billing_subscription_id"), "billing", ["subscription_id"], unique=False)
    op.create_index(op.f("ix_billing_workspace_id"), "billing", ["workspace_id"], unique=False)
    op.add_column("subscriptions", sa.Column("last_charge_timestamp", UTCDateTime(timezone=True), nullable=True))
    op.add_column("subscriptions", sa.Column("next_charge_timestamp", UTCDateTime(timezone=True), nullable=True))
    # ### end Alembic commands ###
