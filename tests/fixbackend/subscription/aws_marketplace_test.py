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
from typing import Dict, Any

from fixbackend.auth.models import User
from fixbackend.subscription.aws_marketplace import AwsMarketplaceHandler


async def test_handle_subscription(
    aws_marketplace_handler: AwsMarketplaceHandler, user: User, boto_answers: Dict[str, Any]
) -> None:
    boto_answers["ResolveCustomer"] = {"CustomerAWSAccountId": "1", "CustomerIdentifier": "2", "ProductCode": "3"}
    result = await aws_marketplace_handler.subscribed(user, "123")
    assert result is not None
    assert result.customer_aws_account_id == "1"
    assert result.customer_identifier == "2"
    assert result.product_code == "3"
    assert result.user_id == user.id
    assert result.workspace_id is None  # user does not have any workspaces yet
    # subscribe again: will not create a new subscription
    result2 = await aws_marketplace_handler.subscribed(user, "123")
    assert result == result2
