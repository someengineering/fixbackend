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
import uuid
from typing import Annotated, Dict

from fastapi import Depends, Request
from fastapi_users import FastAPIUsers

from fixbackend.auth.dependencies import get_user_manager
from fixbackend.auth.jwt import get_auth_backend
from fixbackend.auth.models import User
from fixbackend.config import get_config
from fixbackend.graph_db.dependencies import GraphDatabaseAccessManagerDependency
from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.ids import OrganizationId, TenantId
from fixbackend.organizations.dependencies import OrganizationServiceDependency

# todo: use dependency injection
fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [get_auth_backend(get_config())])

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
async def get_user_organization_ids(
    user_context: AuthenticatedUser, organization_service: OrganizationServiceDependency
) -> Dict[OrganizationId, TenantId]:
    orgs = await organization_service.list_organizations(user_context.user.id)
    return {org.id: org.tenant_id for org in orgs}


UserOrganizationsDependency = Annotated[Dict[OrganizationId, TenantId], Depends(get_user_organization_ids)]


# TODO: do not use list_organization, but get_organization (cached) and make sure the user can only access "its" tenants
async def get_tenant(
    request: Request, user_context: AuthenticatedUser, organization_service: OrganizationServiceDependency
) -> TenantId:
    current_organization_id = request.path_params["organization_id"]
    orgs = await organization_service.list_organizations(user_context.user.id)
    return [org.tenant_id for org in orgs if org.id == current_organization_id][0]


TenantDependency = Annotated[TenantId, Depends(get_tenant)]


async def get_current_graph_db(
    manager: GraphDatabaseAccessManagerDependency, tenant: TenantDependency
) -> GraphDatabaseAccess:
    access = await manager.get_database_access(tenant)
    if access is None:
        raise AttributeError("No database access found for tenant")
    return access


# This is the dependency that should be used in most parts of the application.
CurrentGraphDbDependency = Annotated[GraphDatabaseAccess, Depends(get_current_graph_db)]
