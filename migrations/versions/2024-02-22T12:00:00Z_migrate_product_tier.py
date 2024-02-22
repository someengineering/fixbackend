from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

# revision identifiers, used by Alembic.
revision: str = "625f5b0ac493"
down_revision: Union[str, None] = "4f583cb5ec57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    try:
        op.add_column("metering", sa.Column("tier", sa.String(length=64), nullable=False, server_default="Free"))
        op.execute("UPDATE metering set tier='Free' WHERE security_tier='FreeAccount'")
        op.execute("UPDATE metering set tier='Plus' WHERE security_tier='PlusAccount'")
        op.execute("UPDATE metering set tier='Business' WHERE security_tier='BusinessAccount'")
        op.execute("UPDATE metering set tier='Enterprise' WHERE security_tier='EnterpriseAccount'")
        op.execute("UPDATE metering set tier='Free' WHERE security_tier not in ('FreeAccount', 'PlusAccount', 'BusinessAccount', 'EnterpriseAccount') ")  # fmt: skip # noqa
        op.drop_column("metering", "security_tier")
    except OperationalError:
        pass  # column already exists
    try:
        op.add_column("organization", sa.Column("tier", sa.String(length=64), nullable=False, server_default="Free"))
        op.execute("UPDATE organization set tier='Free' WHERE security_tier='FreeAccount'")
        op.execute("UPDATE organization set tier='Plus' WHERE security_tier='PlusAccount'")
        op.execute("UPDATE organization set tier='Business' WHERE security_tier='BusinessAccount'")
        op.execute("UPDATE organization set tier='Enterprise' WHERE security_tier='EnterpriseAccount'")
        op.execute("UPDATE organization set tier='Free' WHERE security_tier not in ('FreeAccount', 'PlusAccount', 'BusinessAccount', 'EnterpriseAccount') ")  # fmt: skip # noqa
        op.drop_column("organization", "security_tier")
    except OperationalError:
        pass  # column already exists

    op.execute("UPDATE billing set tier='Free' WHERE tier='FreeAccount' ")  # fmt: skip # noqa
    op.execute("UPDATE billing set tier='Plus' WHERE tier='PlusAccount'")
    op.execute("UPDATE billing set tier='Business' WHERE tier='BusinessAccount'")
    op.execute("UPDATE billing set tier='Enterprise' WHERE tier='EnterpriseAccount'")
    op.execute("UPDATE billing set tier='Free' WHERE tier not in ('FreeAccount', 'PlusAccount', 'BusinessAccount', 'EnterpriseAccount') ")  # fmt: skip # noqa
