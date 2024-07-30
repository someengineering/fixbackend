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

from datetime import datetime
from typing import List, Optional

from attrs import frozen
from fixcloudutils.util import utc

from fixbackend.config import trial_period_duration
from fixbackend.ids import InvitationId, SubscriptionId, WorkspaceId, UserId, ExternalId, ProductTier
from fixbackend.permissions.models import Roles


@frozen
class Workspace:
    id: WorkspaceId
    slug: str
    name: str
    external_id: ExternalId
    owner_id: UserId
    members: List[UserId]
    selected_product_tier: ProductTier  # only use it to show the user the tier they selected in the UI
    created_at: datetime
    updated_at: datetime
    subscription_id: Optional[SubscriptionId] = None
    payment_on_hold_since: Optional[datetime] = None
    highest_current_cycle_tier: Optional[ProductTier] = (
        None  # which tier we saw as the highest until the end of the billing cycle
    )
    current_cycle_ends_at: Optional[datetime] = None  # when the active product tier ends, typically end of the month
    move_to_free_acknowledged_at: Optional[datetime] = None  # only set for list_workspaces when the user_id is provided
    free_tier_cleanup_done_at: Optional[datetime] = None

    # this is the product tier that is active for the workspace at the moment
    # it is based on the highest tier we saw during the billing cycle
    # when the billing cycle ends, we look at the selected_product_tier
    #
    # billing will record usages with every collect based on this method, and then will take
    # the highest tier from the usage metrict to determine on which tier you should be billed
    def current_product_tier(self) -> ProductTier:
        if self.current_cycle_ends_at and self.current_cycle_ends_at > utc():
            if self.highest_current_cycle_tier:
                return max(self.highest_current_cycle_tier, self.selected_product_tier)
        return self.selected_product_tier

    def all_users(self) -> List[UserId]:
        unique = set(self.members)
        unique.add(self.owner_id)
        return list(unique)

    def trial_end_days(self) -> Optional[int]:
        if self.current_product_tier() == ProductTier.Trial:
            return max((self.created_at + trial_period_duration() - utc()).days, 0)
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
    role: Roles
    expires_at: datetime
    accepted_at: Optional[datetime]
