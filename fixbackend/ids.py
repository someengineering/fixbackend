from typing import NewType
from uuid import UUID

TenantId = NewType("TenantId", UUID)
InvitationId = NewType("InvitationId", UUID)
UserId = NewType("UserId", UUID)
