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
from fixcloudutils.redis.event_stream import MessageContext
from fixcloudutils.util import utc
from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.cloud_accounts.models import CloudAccount, AwsCloudAccess
from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.dispatcher.dispatcher_service import DispatcherService
from fixbackend.dispatcher.next_run_repository import NextRunRepository
from fixbackend.ids import CloudAccountId
from fixbackend.organizations.models import Organization


@pytest.mark.asyncio
async def test_receive_created(
    dispatcher: DispatcherService,
    session: AsyncSession,
    cloud_account_repository: CloudAccountRepository,
    next_run_repository: NextRunRepository,
    organization: Organization,
) -> None:
    # create a cloud account
    cloud_account_id = CloudAccountId(uuid.uuid1())
    await cloud_account_repository.create(
        CloudAccount(cloud_account_id, organization.id, AwsCloudAccess("123", organization.external_id, "test"))
    )
    await dispatcher.process_message(
        {"id": str(cloud_account_id)}, MessageContext("test", "cloud_account_created", "test", utc(), utc())
    )
