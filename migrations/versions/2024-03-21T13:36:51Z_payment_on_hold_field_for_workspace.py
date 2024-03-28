"""payment on hold field for workspace

Revision ID: bd81f26e562a
Revises: f00a78f4ef30
Create Date: 2024-03-21 13:36:51.545668+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from fixbackend.sqlalechemy_extensions import UTCDateTime


# revision identifiers, used by Alembic.
revision: str = "bd81f26e562a"
down_revision: Union[str, None] = "f00a78f4ef30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column("organization", sa.Column("payment_on_hold_since", UTCDateTime(timezone=True), nullable=True))
    op.create_index(
        op.f("ix_organization_payment_on_hold_since"), "organization", ["payment_on_hold_since"], unique=False
    )
    # ### end Alembic commands ###