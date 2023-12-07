"""support invitation by email

Revision ID: e4745194c033
Revises: d294f6e4b5dc
Create Date: 2023-12-06 15:31:39.912886+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "e4745194c033"
down_revision: Union[str, None] = "d294f6e4b5dc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###

    # user_email is not nullable, so we need to drop all existing invites
    op.execute("TRUNCATE TABLE organization_invite")

    op.add_column("organization_invite", sa.Column("user_email", sa.String(length=320), nullable=False))
    op.add_column("organization_invite", sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organization_invite", sa.Column("version_id", sa.Integer(), nullable=False, server_default="0"))
    op.alter_column("organization_invite", "user_id", existing_type=mysql.CHAR(length=36), nullable=True)
    op.create_unique_constraint(None, "organization_invite", ["user_email"])
    # ### end Alembic commands ###