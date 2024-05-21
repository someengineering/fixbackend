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

from fixbackend.cloud_accounts.gcp_service_account_repo import GcpServiceAccountKeyRepository
from fixbackend.types import AsyncSessionMaker
from fixbackend.workspaces.models import Workspace
from fixcloudutils.util import utc


@pytest.mark.asyncio
async def test_store_gcp_service_account(
    async_session_maker: AsyncSessionMaker,
    workspace: Workspace,
) -> None:
    gcp_repo = GcpServiceAccountKeyRepository(session_maker=async_session_maker)

    gcp_sa_json = "some json"

    gcp_service_account = await gcp_repo.create(workspace.id, gcp_sa_json)

    assert gcp_service_account.can_access_sa is None
    assert gcp_service_account.tenant_id == workspace.id
    assert gcp_service_account.value == gcp_sa_json
    assert gcp_service_account.created_at is not None
    assert gcp_service_account.updated_at is not None

    same_acc = await gcp_repo.get(gcp_service_account.id)
    assert same_acc == gcp_service_account

    assert await gcp_repo.list_created_after(utc() + timedelta(minutes=5)) == []
    assert await gcp_repo.list_created_after(utc() - timedelta(minutes=5)) == [same_acc]

    assert await gcp_repo.list_created_before(utc() - timedelta(minutes=5)) == []
    assert await gcp_repo.list_created_before(utc() + timedelta(minutes=5)) == [same_acc]

    await gcp_repo.update_status(gcp_service_account.id, can_access_sa=True)
    updated_acc = await gcp_repo.get(gcp_service_account.id)

    assert updated_acc
    assert updated_acc.can_access_sa is True
    assert updated_acc.updated_at >= gcp_service_account.updated_at
    assert updated_acc.created_at == gcp_service_account.created_at
    assert updated_acc.tenant_id == gcp_service_account.tenant_id
    assert updated_acc.value == gcp_service_account.value

    await gcp_repo.delete(gcp_service_account.id)
    assert await gcp_repo.get(gcp_service_account.id) is None
