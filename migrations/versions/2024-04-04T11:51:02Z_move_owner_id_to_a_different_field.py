"""move owner_id to a different field

Revision ID: 51b7e006cee5
Revises: afe34c8861f5
Create Date: 2024-04-04 11:51:02.458084+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from fastapi_users_db_sqlalchemy.generics import GUID

# revision identifiers, used by Alembic.
revision: str = "51b7e006cee5"
down_revision: Union[str, None] = "afe34c8861f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # create a new column and a field
    op.add_column("organization", sa.Column("owner_id", GUID, nullable=False))
    op.create_index(op.f("ix_organization_owner_id"), "organization", ["owner_id"], unique=False)

    # insert data from the owners
    op.execute(
        """
        UPDATE organization
        SET owner_id = (
            SELECT user_id
            FROM organization_owners
            WHERE organization_owners.organization_id = organization.id
            LIMIT 1
        )
        """
    )

    # make the new column not nullable and add a foreign key
    # op.alter_column("organization", "owner_id", existing_type=GUID(), nullable=False)
    op.create_foreign_key(None, "organization", "user", ["owner_id"], ["id"])
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### end Alembic commands ###
    pass
