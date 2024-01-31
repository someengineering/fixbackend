from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from fastapi_users_db_sqlalchemy import GUID

from fixbackend.notification.model import WorkspaceAlert
from fixbackend.sqlalechemy_extensions import UTCDateTime, AsJsonPydantic

revision: str = "84cfaaf4b05a"
down_revision: Union[str, None] = "a709a16b4e0f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspace_alert_config",
        sa.Column("workspace_id", GUID(), nullable=False),
        sa.Column("alerts", AsJsonPydantic(WorkspaceAlert), nullable=False),
        sa.Column("created_at", UTCDateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    op.create_table(
        "notification_provider_config",
        sa.Column("workspace_id", GUID(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("messaging_config", sa.JSON(), nullable=False),
        sa.Column("created_at", UTCDateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UTCDateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "provider"),
    )
