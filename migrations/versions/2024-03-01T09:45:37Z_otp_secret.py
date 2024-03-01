"""otp_secret

Revision ID: 56e928e9255b
Revises: 625f5b0ac493
Create Date: 2024-03-01 09:45:37.961934+00:00

"""

import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "56e928e9255b"
down_revision: Union[str, None] = "625f5b0ac493"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    try:
        op.add_column("user", sa.Column("otp_secret", sa.String(length=64), nullable=True))
        op.add_column("user", sa.Column("is_mfa_active", sa.Boolean(), server_default=sa.false(), nullable=False))
    except Exception:
        logging.warning("Could not add column otp_secret to user table")
