"""tutorial_emails

Revision ID: 992c435d91ef
Revises: 4345cdee91d1
Create Date: 2024-04-02 08:42:50.934348+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import DefaultClause, text

from fixbackend.sqlalechemy_extensions import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "992c435d91ef"
down_revision: Union[str, None] = "4345cdee91d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_notification_settings", sa.Column("tutorial", sa.Boolean(), nullable=False))
    op.add_column(
        "user_notification_settings",
        sa.Column("created_at", UTCDateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.add_column(
        "user_notification_settings",
        sa.Column(
            "updated_at",
            UTCDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            server_onupdate=DefaultClause(text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
        ),
    )
