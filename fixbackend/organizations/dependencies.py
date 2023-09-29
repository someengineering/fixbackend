from typing import Annotated

from fastapi import Depends

from fixbackend.db import AsyncSessionDependency
from fixbackend.dependencies import FixDependency
from fixbackend.organizations.service import OrganizationService


async def get_organization_service(session: AsyncSessionDependency, fix: FixDependency) -> OrganizationService:
    return OrganizationService(session, fix.graph_database_access)


OrganizationServiceDependency = Annotated[OrganizationService, Depends(get_organization_service)]
