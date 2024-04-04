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

from datetime import datetime, timedelta
from typing import List, Optional

from attrs import frozen
from fixcloudutils.util import utc

from fixbackend.ids import InvitationId, SubscriptionId, WorkspaceId, UserId, ExternalId, ProductTier


@frozen
class Workspace:
    id: WorkspaceId
    slug: str
    name: str
    external_id: ExternalId
    owner_id: UserId
    members: List[UserId]
    product_tier: ProductTier
    created_at: datetime
    updated_at: datetime
    subscription_id: Optional[SubscriptionId] = None
    payment_on_hold_since: Optional[datetime] = None

    def all_users(self) -> List[UserId]:
        unique = set(self.members)
        unique.add(self.owner_id)
        return list(unique)

    def trial_end_days(self) -> Optional[int]:
        if self.product_tier == ProductTier.Trial:
            return max((self.created_at + timedelta(days=14, hours=12) - utc()).days, 0)
        return None

    # for the cases of the trial period ended
    def paid_tier_access(self, user_id: UserId) -> bool:
        # owner can always access
        if user_id == self.owner_id:
            return True

        if self.payment_on_hold_since is not None:
            return False

        # if trial period is over, no access
        if trial_end := self.trial_end_days():
            if trial_end == 0 and self.subscription_id is None:
                return False

        return True


@frozen
class WorkspaceInvitation:
    id: InvitationId
    workspace_id: WorkspaceId
    email: str
    expires_at: datetime
    accepted_at: Optional[datetime]
