"""free tier account  removal

Revision ID: dbe8f626f045
Revises: 2e39a90ed4ac
Create Date: 2024-07-30 17:09:40.293980+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from fixbackend.sqlalechemy_extensions import UTCDateTime


# revision identifiers, used by Alembic.
revision: str = "dbe8f626f045"
down_revision: Union[str, None] = "2e39a90ed4ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("organization", sa.Column("tier_updated_at", UTCDateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_organization_tier_updated_at"), "organization", ["tier_updated_at"], unique=False)


def downgrade() -> None:
    pass
