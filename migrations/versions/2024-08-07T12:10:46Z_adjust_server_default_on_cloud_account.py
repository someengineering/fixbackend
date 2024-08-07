"""adjust server default on cloud account

Revision ID: 9b6e2089db75
Revises: 1e4ccaf4e087
Create Date: 2024-08-07 12:10:46.359929+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "9b6e2089db75"
down_revision: Union[str, None] = "1e4ccaf4e087"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    inspector = inspect(op.get_bind())
    columns = inspector.get_columns("cloud_account")
    if any(column["name"] == "last_scan_resources_errors" for column in columns):
        op.drop_column("cloud_account", "last_scan_resources_errors")

    op.add_column(
        "cloud_account",
        sa.Column("last_scan_resources_errors", sa.Integer(), nullable=False, server_default="0"),
    )
