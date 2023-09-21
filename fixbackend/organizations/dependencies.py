from typing import Annotated, List
from uuid import UUID

from fastapi import Depends
from fixbackend.auth.dependencies import AuthenticatedUser
from fixbackend.organizations.service import OrganizationServiceDependency


# todo: take this info from the user's JWT
async def get_user_tenants(
    user_context: AuthenticatedUser, organization_service: OrganizationServiceDependency
) -> List[UUID]:
    orgs = await organization_service.list_organizations(user_context.user.id)
    return [org.tenant_id for org in orgs]


UserTenantsDependency = Annotated[List[UUID], Depends(get_user_tenants)]
