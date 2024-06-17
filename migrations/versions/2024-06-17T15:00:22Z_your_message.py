"""your message

Revision ID: 377be0a4392e
Revises: 167047784340
Create Date: 2024-06-17 15:00:22.208970+00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "377be0a4392e"
down_revision: Union[str, None] = "167047784340"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("azure_subscription_credential", "azure_subscription_id")
