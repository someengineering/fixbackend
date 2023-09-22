from typing import NewType
from uuid import UUID

OrganizationId = NewType("OrganizationId", UUID)
TenantId = NewType("TenantId", UUID)
