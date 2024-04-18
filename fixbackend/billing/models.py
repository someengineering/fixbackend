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


from typing import Union, List
from fixbackend.ids import SubscriptionId
from attrs import frozen


class PaymentMethods:
    @frozen
    class AwsSubscription:
        subscription_id: SubscriptionId

    @frozen
    class StripeSubscription:
        subscription_id: SubscriptionId

    @frozen
    class NoPaymentMethod:
        pass


PaymentMethod = Union[PaymentMethods.AwsSubscription, PaymentMethods.StripeSubscription, PaymentMethods.NoPaymentMethod]


@frozen
class WorkspacePaymentMethods:
    current: PaymentMethod
    available: List[PaymentMethod]
