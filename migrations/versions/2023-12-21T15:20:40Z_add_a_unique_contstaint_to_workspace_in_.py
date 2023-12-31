"""add a unique contstaint to workspace in subscriptions

Revision ID: a709a16b4e0f
Revises: 917c74178e81
Create Date: 2023-12-21 15:20:40.941195+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a709a16b4e0f"
down_revision: Union[str, None] = "917c74178e81"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index("ix_subscriptions_workspace_id", table_name="subscriptions")
    op.create_index(op.f("ix_subscriptions_workspace_id"), "subscriptions", ["workspace_id"], unique=True)
    # ### end Alembic commands ###
