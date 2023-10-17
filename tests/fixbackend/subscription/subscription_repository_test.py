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
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from fixbackend.ids import PaymentMethodId, UserId, WorkspaceId
from fixbackend.subscription.models import AwsMarketplaceSubscription
from fixbackend.subscription.subscription_repository import (
    SubscriptionRepository,
    SubscriptionEntity,
)


async def test_create_entry(subscription_repository: SubscriptionRepository, session: AsyncSession) -> None:
    id = PaymentMethodId(uuid4())
    user_id = UserId(uuid4())
    entity = AwsMarketplaceSubscription(
        id=id,
        user_id=user_id,
        workspace_id=WorkspaceId(uuid4()),
        customer_identifier="123",
        customer_aws_account_id="123",
        product_code="123",
        active=True,
    )
    await subscription_repository.create(entity)
    assert await subscription_repository.aws_marketplace_subscription(user_id, entity.customer_identifier) is not None
    assert await subscription_repository.aws_marketplace_subscription(user_id, "124") is None
    result = await session.get(SubscriptionEntity, id)
    assert result is not None
