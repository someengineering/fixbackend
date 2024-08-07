"""add index on workspace slug

Revision ID: 8907ec70cc77
Revises: 51b7e006cee5
Create Date: 2024-04-10 11:28:30.055276+00:00

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "8907ec70cc77"
down_revision: Union[str, None] = "51b7e006cee5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###

    inspector = inspect(op.get_bind())

    constraints = inspector.get_unique_constraints("organization")
    for constraint in constraints:
        if constraint["column_names"] == ["slug"] and constraint["name"]:
            op.drop_constraint(constraint["name"], "organization", type_="unique")

    op.drop_index("slug", table_name="organization", if_exists=True)
    op.create_index(op.f("ix_organization_slug"), "organization", ["slug"], unique=True)
    # ### end Alembic commands ###


def downgrade() -> None:
    pass
    # ### commands auto generated by Alembic - please adjust! ###
    # ### end Alembic commands ###
