"""add gcp json table

Revision ID: 82a1dd1f28b4
Revises: cd7a04e7394c
Create Date: 2024-05-16 13:32:10.226773+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from fixbackend.sqlalechemy_extensions import UTCDateTime
from fastapi_users_db_sqlalchemy.generics import GUID

# revision identifiers, used by Alembic.
revision: str = "82a1dd1f28b4"
down_revision: Union[str, None] = "cd7a04e7394c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gcp_service_account_key",
        sa.Column("id", GUID, nullable=False),
        sa.Column("tenant_id", GUID, nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("can_access_sa", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            UTCDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            UTCDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organization.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_gcp_service_account_key_tenant_id"), "gcp_service_account_key", ["tenant_id"], unique=True)


def downgrade() -> None:
    pass
