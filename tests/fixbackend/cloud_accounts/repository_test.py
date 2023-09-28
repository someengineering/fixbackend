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

import uuid

import pytest

from fixbackend.ids import CloudAccountId, ExternalId
from fixbackend.cloud_accounts.repository import CloudAccountRepositoryImpl
from fixbackend.db import AsyncSessionMaker
from fixbackend.cloud_accounts.models import CloudAccount, AwsCloudAccess
from fixbackend.organizations.service import OrganizationService
from fixbackend.auth.models import User


@pytest.mark.asyncio
async def test_create_cloud_account(
    async_session_maker: AsyncSessionMaker, organisation_service: OrganizationService, user: User
) -> None:
    cloud_account_repository = CloudAccountRepositoryImpl(session_maker=async_session_maker)
    org = await organisation_service.create_organization("foo", "foo", user)
    tenant_id = org.id
    account = CloudAccount(
        id=CloudAccountId(uuid.uuid4()),
        tenant_id=tenant_id,
        access=AwsCloudAccess(
            account_id="123456789012",
            role_name="foo",
            external_id=ExternalId(uuid.uuid4()),
        ),
    )

    # create
    await cloud_account_repository.create(cloud_account=account)
    stored_account = await cloud_account_repository.get(id=account.id)

    assert account == stored_account
