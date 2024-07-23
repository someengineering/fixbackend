"""sync metering records fields lengths to cloud accounts

Revision ID: 917c74178e81
Revises: fa6b6587c907
Create Date: 2023-12-14 12:47:37.101341+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "917c74178e81"
down_revision: Union[str, None] = "fa6b6587c907"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column(
        "cloud_account",
        "cloud",
        existing_type=postgresql.VARCHAR(length=12),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.alter_column(
        "cloud_account",
        "account_id",
        existing_type=postgresql.VARCHAR(length=12),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.alter_column(
        "metering",
        "cloud",
        existing_type=postgresql.VARCHAR(length=10),
        type_=sa.String(length=64),
        existing_nullable=True,
    )
    op.alter_column(
        "metering",
        "account_id",
        existing_type=postgresql.VARCHAR(length=36),
        type_=sa.String(length=256),
        existing_nullable=True,
    )
    op.alter_column(
        "metering",
        "account_name",
        existing_type=postgresql.VARCHAR(length=255),
        type_=sa.String(length=256),
        existing_nullable=True,
    )
    # ### end Alembic commands ###
