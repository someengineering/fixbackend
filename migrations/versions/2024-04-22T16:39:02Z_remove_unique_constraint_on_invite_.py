"""remove unique constraint on invite emails

Revision ID: 95147d1ca43e
Revises: cfc3950ae404
Create Date: 2024-04-22 16:39:02.254279+00:00

"""

from sqlalchemy import inspect
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "95147d1ca43e"
down_revision: Union[str, None] = "cfc3950ae404"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    inspector = inspect(op.get_bind())

    constraints = inspector.get_unique_constraints("organization_invite")
    for constraint in constraints:
        if constraint["column_names"] == ["user_email"] and constraint["name"]:
            op.drop_constraint(constraint["name"], "organization_invite", type_="unique")

    # ### end Alembic commands ###


def downgrade() -> None:
    pass
    # ### commands auto generated by Alembic - please adjust! ###
    # ### end Alembic commands ###
