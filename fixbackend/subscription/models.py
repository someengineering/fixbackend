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
from datetime import datetime
from typing import Union, Optional, TypeVar, ClassVar

from attr import frozen

from fixbackend.ids import SubscriptionId, UserId, StripeSubscriptionId, StripeCustomerId, WorkspaceId


@frozen
class AwsMarketplaceSubscription:
    kind: ClassVar[str] = "aws_marketplace"
    id: SubscriptionId
    user_id: Optional[UserId]
    customer_identifier: str
    customer_aws_account_id: str
    product_code: str
    active: bool
    last_charge_timestamp: Optional[datetime]
    next_charge_timestamp: Optional[datetime]


@frozen
class StripeSubscription:
    kind: ClassVar[str] = "stripe"
    id: SubscriptionId
    workspace_id: Optional[WorkspaceId]
    customer_identifier: StripeCustomerId
    stripe_subscription_id: StripeSubscriptionId
    active: bool
    last_charge_timestamp: Optional[datetime]
    next_charge_timestamp: Optional[datetime]


# Multiple payment methods are possible, but for now we only support AWS Marketplace
SubscriptionMethod = Union[AwsMarketplaceSubscription, StripeSubscription]

SubscriptionMethodType = TypeVar("SubscriptionMethodType", bound=SubscriptionMethod)
