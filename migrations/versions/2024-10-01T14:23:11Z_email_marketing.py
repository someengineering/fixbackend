"""
user_notification_settings: add marketing column
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "2c3086217445"
down_revision: Union[str, None] = "1e4ccaf4e087"


def upgrade() -> None:
    op.add_column(
        "user_notification_settings",
        sa.Column(
            "marketing",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )
