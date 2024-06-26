"""support roles when inviting users

Revision ID: dc3245ee9167
Revises: 9e047608dacc
Create Date: 2024-04-24 08:54:40.531627+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "dc3245ee9167"
down_revision: Union[str, None] = "9e047608dacc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column("organization_invite", sa.Column("role", sa.Integer(), server_default="0", nullable=False))
    # ### end Alembic commands ###


def downgrade() -> None:
    pass
