from typing import NewType
from uuid import UUID

WorkspaceId = NewType("WorkspaceId", UUID)
InvitationId = NewType("InvitationId", UUID)
UserId = NewType("UserId", UUID)
CloudAccountId = NewType("CloudAccountId", UUID)
ExternalId = NewType("ExternalId", UUID)
