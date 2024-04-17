#  Copyright (c) 2024. Some Engineering
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import DefaultClause, text
from sqlalchemy.dialects import mysql

from fixbackend.sqlalechemy_extensions import UTCDateTime, GUID

# revision identifiers, used by Alembic.
revision: str = "cfc3950ae404"
down_revision: Union[str, None] = "8907ec70cc77"


def upgrade() -> None:
    op.create_table(
        "stripe_customers",
        sa.Column("workspace_id", GUID(), nullable=False),
        sa.Column("customer_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", UTCDateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "updated_at",
            UTCDateTime(timezone=True),
            server_default=sa.text("now()"),
            server_onupdate=DefaultClause(text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("workspace_id"),
        sa.UniqueConstraint("customer_id"),
    )
    # add stripe_subscription columns (nullable)
    op.add_column("subscriptions", sa.Column("stripe_subscription_id", sa.String(length=128), nullable=True))
    op.add_column("subscriptions", sa.Column("stripe_customer_identifier", sa.String(length=128), nullable=True))
    # define the aws columns as nullable
    op.alter_column("subscriptions", "aws_customer_identifier", existing_type=mysql.VARCHAR(length=128), nullable=True)
    op.alter_column("subscriptions", "aws_product_code", existing_type=mysql.VARCHAR(length=128), nullable=True)
