from typing import Annotated

from fastapi import Depends

from fixbackend.db import AsyncSessionDependency
from fixbackend.dependencies import FixDependency
from fixbackend.organizations.repository import OrganizationRepository


async def get_organization_service(session: AsyncSessionDependency, fix: FixDependency) -> OrganizationRepository:
    return OrganizationRepository(session, fix.graph_database_access)


OrganizationServiceDependency = Annotated[OrganizationRepository, Depends(get_organization_service)]
