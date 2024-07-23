"""remove kvstore

Revision ID: 2e39a90ed4ac
Revises: 861137e5214c
Create Date: 2024-07-22 16:57:58.024629+00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2e39a90ed4ac"
down_revision: Union[str, None] = "861137e5214c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("key_value_json")
    # ### end Alembic commands ###


def downgrade() -> None:
    pass
