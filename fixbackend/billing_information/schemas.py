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

from pydantic import BaseModel, Field

from typing import Optional

from fixbackend.ids import BillingId, SecurityTier, SubscriptionId, WorkspaceId
from fixbackend.subscription.models import BillingEntry
from enum import Enum

from fixbackend.workspaces.models import Workspace


class BillingEntryRead(BaseModel):
    id: BillingId = Field(description="Id of the billing entry")
    workspace_id: WorkspaceId = Field(description="The workspace's unique identifier")
    subscription_id: SubscriptionId = Field(description="The subscription's unique identifier")
    tier: SecurityTier = Field(description="Security tier during the billing period")
    period_start: datetime = Field(description="The start of the billing period")
    period_end: datetime = Field(description="The end of the billing period")
    nr_of_accounts_charged: int = Field(description="The number of accounts charged during the billing period")

    @staticmethod
    def from_model(billing_entry: BillingEntry) -> "BillingEntryRead":
        return BillingEntryRead(
            id=billing_entry.id,
            workspace_id=billing_entry.workspace_id,
            subscription_id=billing_entry.subscription_id,
            tier=SecurityTier(billing_entry.tier),
            period_start=billing_entry.period_start,
            period_end=billing_entry.period_end,
            nr_of_accounts_charged=billing_entry.nr_of_accounts_charged,
        )


class PaymentMethod(str, Enum):
    AWS = "aws_marketplace"


class SecurityTierJson(str, Enum):
    Free = "free"
    Foundational = "foundational"
    HighSecurity = "high_security"


class WorkspaceBillingSettings(BaseModel):
    payment_method: Optional[PaymentMethod] = Field(description="The payment method used for this workspace")
    security_tier: SecurityTierJson = Field(description="The security tier of this workspace")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "payment_method": "aws_marketplace",
                    "security_tier": "free",
                }
            ]
        }
    }

    @staticmethod
    def from_model(workspace: Workspace) -> "WorkspaceBillingSettings":
        def tier(workspace: Workspace) -> SecurityTierJson:
            match workspace.security_tier:
                case SecurityTier.Free:
                    return SecurityTierJson.Free
                case SecurityTier.Foundational:
                    return SecurityTierJson.Foundational
                case SecurityTier.HighSecurity:
                    return SecurityTierJson.HighSecurity

        return WorkspaceBillingSettings(
            payment_method=PaymentMethod.AWS,
            security_tier=tier(workspace),
        )
