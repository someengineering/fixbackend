#  Copyright (c) 2024. Some Engineering
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


from datetime import timedelta
import pytest

from fixbackend.cloud_accounts.azure_subscription_repo import AzureSubscriptionCredentialsRepository
from fixbackend.ids import CloudAccountId
from fixbackend.types import AsyncSessionMaker
from fixbackend.workspaces.models import Workspace
from fixcloudutils.util import utc


@pytest.mark.asyncio
async def test_store_azure_subscription(
    async_session_maker: AsyncSessionMaker,
    workspace: Workspace,
) -> None:
    azure_repo = AzureSubscriptionCredentialsRepository(session_maker=async_session_maker)

    azure_subscription_id = CloudAccountId("some id")
    azure_tenant_id = "some tenant id"
    client_id = "some client id"
    client_secret = "foo_bar"
    azure_credentials = await azure_repo.upsert(
        workspace.id, azure_subscription_id, azure_tenant_id, client_id, client_secret
    )

    assert azure_credentials.can_access_azure_account is None
    assert azure_credentials.tenant_id == workspace.id
    assert azure_credentials.azure_subscription_id == azure_subscription_id
    assert azure_credentials.azure_tenant_id == azure_tenant_id
    assert azure_credentials.client_id == client_id
    assert azure_credentials.client_secret == client_secret
    assert azure_credentials.created_at is not None
    assert azure_credentials.updated_at is not None

    same_acc = await azure_repo.get(azure_credentials.id)
    assert same_acc == azure_credentials

    assert await azure_repo.list_created_after(utc() + timedelta(minutes=5)) == []
    assert await azure_repo.list_created_after(utc() - timedelta(minutes=5)) == [same_acc]

    assert await azure_repo.list_created_before(utc() - timedelta(minutes=5)) == []
    assert await azure_repo.list_created_before(utc() + timedelta(minutes=5)) == [same_acc]

    assert await azure_repo.get_by_tenant(workspace.id) == same_acc

    await azure_repo.update_status(azure_credentials.id, can_access_accounts=True)
    updated_acc = await azure_repo.get(azure_credentials.id)

    assert updated_acc
    assert updated_acc.can_access_azure_account is True
    assert updated_acc.updated_at >= azure_credentials.updated_at
    assert updated_acc.created_at == azure_credentials.created_at
    assert updated_acc.tenant_id == azure_credentials.tenant_id
    assert updated_acc.azure_subscription_id == azure_subscription_id
    assert updated_acc.azure_tenant_id == azure_tenant_id
    assert updated_acc.client_id == client_id
    assert updated_acc.client_secret == client_secret

    await azure_repo.delete(azure_credentials.id)
    assert await azure_repo.get(azure_credentials.id) is None
