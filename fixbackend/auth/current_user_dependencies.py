#  Copyright (c) 2023. Some Engineering
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
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
from uuid import UUID
from typing import Annotated, Set

from fastapi import Depends, HTTPException, Request, status
from fastapi_users import FastAPIUsers

from fixbackend.auth.dependencies import get_user_manager
from fixbackend.auth.jwt import get_auth_backend
from fixbackend.auth.models import User
from fixbackend.config import get_config
from fixbackend.dependencies import FixDependency
from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.ids import TenantId
from fixbackend.organizations.repository import OrganizationRepositoryDependency

# todo: use dependency injection
fastapi_users = FastAPIUsers[User, UUID](get_user_manager, [get_auth_backend(get_config())])

# the value below is a dependency itself
get_current_active_verified_user = fastapi_users.current_user(active=True, verified=True)


class CurrentVerifiedActiveUserDependencies:
    def __init__(
        self,
        user: Annotated[User, Depends(get_current_active_verified_user)],
    ) -> None:
        self.user = user


AuthenticatedUser = Annotated[CurrentVerifiedActiveUserDependencies, Depends()]


# todo: take this info from the user's JWT
async def get_user_tenants_ids(
    user_context: AuthenticatedUser, organization_service: OrganizationRepositoryDependency
) -> Set[TenantId]:
    orgs = await organization_service.list_organizations(user_context.user.id)
    return {org.id for org in orgs}


UserTenantsDependency = Annotated[Set[TenantId], Depends(get_user_tenants_ids)]


# TODO: do not use list_organization, but get_organization (cached) and make sure the user can only access "its" tenants
async def get_tenant(
    request: Request, user_context: AuthenticatedUser, organization_service: OrganizationRepositoryDependency
) -> TenantId:
    organization_id = request.path_params.get("organization_id")
    try:
        tenant_id = TenantId(UUID(organization_id))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid organization id")
    orgs = await organization_service.list_organizations(user_context.user.id)
    org_ids: Set[TenantId] = {org.id for org in orgs}
    if tenant_id not in org_ids:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="You're not a member of this organization")
    return tenant_id


TenantDependency = Annotated[TenantId, Depends(get_tenant)]


async def get_current_graph_db(fix: FixDependency, tenant: TenantDependency) -> GraphDatabaseAccess:
    access = await fix.graph_database_access.get_database_access(tenant)
    if access is None:
        raise AttributeError("No database access found for tenant")
    return access


# This is the dependency that should be used in most parts of the application.
CurrentGraphDbDependency = Annotated[GraphDatabaseAccess, Depends(get_current_graph_db)]
