"""drop tenant id

Revision ID: b768e81c0d5c
Revises: 995b51027ef6
Create Date: 2023-09-26 19:17:30.837516+00:00

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b768e81c0d5c"
down_revision: Union[str, None] = "995b51027ef6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("organization", "tenant_id")
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###
