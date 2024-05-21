"""store service account key id for gcp cloud accounts

Revision ID: 93656ab46b96
Revises: 82a1dd1f28b4
Create Date: 2024-05-21 14:20:17.480074+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from fastapi_users_db_sqlalchemy.generics import GUID


# revision identifiers, used by Alembic.
revision: str = "93656ab46b96"
down_revision: Union[str, None] = "82a1dd1f28b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cloud_account", sa.Column("gcp_service_account_key_id", GUID, nullable=True))


def downgrade() -> None:
    pass
