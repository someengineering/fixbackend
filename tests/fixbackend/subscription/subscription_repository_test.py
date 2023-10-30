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
from datetime import timezone, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.ids import SubscriptionId, UserId, WorkspaceId
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.subscription.subscription_repository import (
    SubscriptionRepository,
    SubscriptionEntity,
)


async def test_crud_entry(subscription_repository: SubscriptionRepository, session: AsyncSession) -> None:
    id = SubscriptionId(uuid4())
    user_id = UserId(uuid4())
    cid = "some-customer-id"
    now = datetime(2021, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    entity = AwsMarketplaceSubscription(
        id=id,
        user_id=user_id,
        workspace_id=WorkspaceId(uuid4()),
        customer_identifier=cid,
        customer_aws_account_id="123",
        product_code="123",
        active=True,
        last_charge_timestamp=now,
        next_charge_timestamp=now,
    )
    # create entity
    await subscription_repository.create(entity)
    # make sure the value is stored in the database
    assert await session.get(SubscriptionEntity, id) is not None
    # load existing entity
    assert await subscription_repository.aws_marketplace_subscription(user_id, cid) is not None
    # try to load non-existing entity
    assert await subscription_repository.aws_marketplace_subscription(user_id, "n/a") is None
    # mark entity as inactive
    assert await subscription_repository.mark_aws_marketplace_subscriptions(cid, False) == 1
    assert (await session.get(SubscriptionEntity, id)).active is False  # type: ignore
    # mark entity as active
    assert await subscription_repository.mark_aws_marketplace_subscriptions(cid, True) == 1
    assert (await session.get(SubscriptionEntity, id)).active is True  # type: ignore
    # delete entity
    assert await subscription_repository.delete_aws_marketplace_subscriptions(cid) == 1
    # make sure the value is gone
    assert await session.get(SubscriptionEntity, id) is None
