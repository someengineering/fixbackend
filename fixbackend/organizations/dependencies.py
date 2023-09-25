from typing import Annotated

from fastapi import Depends

from fixbackend.db import AsyncSessionDependency
from fixbackend.graph_db.dependencies import GraphDatabaseAccessManagerDependency
from fixbackend.organizations.service import OrganizationService


async def get_organization_service(
    session: AsyncSessionDependency, graph_db_access_manager: GraphDatabaseAccessManagerDependency
) -> OrganizationService:
    return OrganizationService(session, graph_db_access_manager)


OrganizationServiceDependency = Annotated[OrganizationService, Depends(get_organization_service)]
