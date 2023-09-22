from typing import Annotated, Dict

from fastapi import Depends
from fixbackend.auth.dependencies import AuthenticatedUser
from fixbackend.organizations.service import OrganizationServiceDependency
from fixbackend.ids import TenantId, OrganizationId


# todo: take this info from the user's JWT
async def get_user_organization_ids(
    user_context: AuthenticatedUser, organization_service: OrganizationServiceDependency
) -> Dict[OrganizationId, TenantId]:
    orgs = await organization_service.list_organizations(user_context.user.id)
    return {org.id: org.tenant_id for org in orgs}


UserOrganizationsDependency = Annotated[Dict[OrganizationId, TenantId], Depends(get_user_organization_ids)]
