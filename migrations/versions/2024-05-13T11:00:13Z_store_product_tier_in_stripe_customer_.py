"""store product tier in stripe customer table

Revision ID: 57828ccdb2d9
Revises: 855bc1b7b7d1
Create Date: 2024-05-13 11:00:13.574376+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "57828ccdb2d9"
down_revision: Union[str, None] = "855bc1b7b7d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stripe_customers", sa.Column("desired_product_tier", sa.String(length=64), nullable=True))


def downgrade() -> None:
    pass
