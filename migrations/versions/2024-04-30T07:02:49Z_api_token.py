"""api_token

Revision ID: 855bc1b7b7d1
Revises: dc3245ee9167
Create Date: 2024-04-30 06:57:25.699945+00:00

"""

import fastapi_users_db_sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy import DefaultClause, text

from fixbackend.sqlalechemy_extensions import GUID, UTCDateTime

revision: str = "855bc1b7b7d1"
down_revision: str = "dc3245ee9167"


def upgrade() -> None:
    op.create_table(
        "api_token",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("hash", sa.String(length=512), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("user_id", fastapi_users_db_sqlalchemy.generics.GUID(), nullable=False),
        sa.Column("workspace_id", fastapi_users_db_sqlalchemy.generics.GUID(), nullable=True),
        sa.Column("permission", sa.Integer(), nullable=True),
        sa.Column("created_at", UTCDateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "updated_at",
            UTCDateTime(timezone=True),
            server_default=sa.text("now()"),
            server_onupdate=DefaultClause(text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
            nullable=False,
        ),
        sa.Column("last_used_at", UTCDateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["organization.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="unique_user_token_name"),
    )
    # ### end Alembic commands ###
