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

from typing import List, Literal, Optional, Union
from fixbackend.billing.models import PaymentMethods, WorkspacePaymentMethods
from fixbackend.billing import models

from fixbackend.ids import BillingId, ProductTier, SubscriptionId, WorkspaceId
from fixbackend.subscription.models import BillingEntry
from enum import Enum

from fixbackend.workspaces.models import Workspace


class ProductTierRead(str, Enum):
    Trial = "Trial"
    Free = "Free"
    Plus = "Plus"
    Business = "Business"
    Enterprise = "Enterprise"

    def to_tier(self) -> ProductTier:  # pragma: no cover
        match self:
            case ProductTierRead.Trial:
                return ProductTier.Trial
            case ProductTierRead.Free:
                return ProductTier.Free
            case ProductTierRead.Plus:
                return ProductTier.Plus
            case ProductTierRead.Business:
                return ProductTier.Business
            case ProductTierRead.Enterprise:
                return ProductTier.Enterprise

    @staticmethod
    def from_tier(tier: ProductTier) -> "ProductTierRead":  # pragma: no cover
        match tier:
            case ProductTier.Trial:
                return ProductTierRead.Trial
            case ProductTier.Free:
                return ProductTierRead.Free
            case ProductTier.Plus:
                return ProductTierRead.Plus
            case ProductTier.Business:
                return ProductTierRead.Business
            case ProductTier.Enterprise:
                return ProductTierRead.Enterprise


class BillingEntryRead(BaseModel):
    id: BillingId = Field(description="Id of the billing entry")
    workspace_id: WorkspaceId = Field(description="The workspace's unique identifier")
    subscription_id: SubscriptionId = Field(description="The subscription's unique identifier")
    tier: ProductTierRead = Field(description="Product tier during the billing period")
    period_start: datetime = Field(description="The start of the billing period")
    period_end: datetime = Field(description="The end of the billing period")
    nr_of_accounts_charged: int = Field(description="The number of accounts charged during the billing period")

    @staticmethod
    def from_model(billing_entry: BillingEntry) -> "BillingEntryRead":  # pragma: no cover
        return BillingEntryRead(
            id=billing_entry.id,
            workspace_id=billing_entry.workspace_id,
            subscription_id=billing_entry.subscription_id,
            tier=ProductTierRead.from_tier(billing_entry.tier),
            period_start=billing_entry.period_start,
            period_end=billing_entry.period_end,
            nr_of_accounts_charged=billing_entry.nr_of_accounts_charged,
        )


class AwsSubscription(BaseModel):
    method: Literal["aws_marketplace"]
    subscription_id: SubscriptionId = Field(description="Subscription identifier")


class StripeSubscription(BaseModel):
    method: Literal["stripe"]
    subscription_id: SubscriptionId = Field(description="Subscription identifier")


class NoPaymentMethod(BaseModel):
    method: Literal["none"]


PaymentMethod = Union[AwsSubscription, StripeSubscription, NoPaymentMethod]


class WorkspaceBillingSettingsRead(BaseModel):
    workspace_payment_method: PaymentMethod = Field(description="The payment method selected for workspace")
    available_payment_methods: List[PaymentMethod] = Field(description="The payment methods available for workspace")
    product_tier: ProductTierRead = Field(description="The product tier of this workspace")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "workspace_payment_method": {
                        "method": "aws_marketplace",
                        "subscription_id": "00000000-0000-0000-0000-000000000000",
                    },
                    "available_payment_methods": [
                        {
                            "method": "aws_marketplace",
                            "subscription_id": "00000000-0000-0000-0000-000000000000",
                        },
                        {
                            "method": "aws_marketplace",
                            "subscription_id": "00000000-0000-0000-0000-000000000000",
                        },
                        {
                            "method": "none",
                        },
                    ],
                    "product_tier": "Free",
                }
            ]
        }
    }

    @staticmethod
    def from_model(
        workspace: Workspace,
        payment_methods: WorkspacePaymentMethods,
    ) -> "WorkspaceBillingSettingsRead":  # pragma: no cover

        def payment(payment_method: models.PaymentMethod) -> PaymentMethod:
            match payment_method:
                case PaymentMethods.AwsSubscription(subscription_id):
                    return AwsSubscription(method="aws_marketplace", subscription_id=subscription_id)
                case PaymentMethods.StripeSubscription(subscription_id):
                    return AwsSubscription(method="aws_marketplace", subscription_id=subscription_id)
                case PaymentMethods.NoPaymentMethod():
                    return NoPaymentMethod(method="none")

        return WorkspaceBillingSettingsRead(
            workspace_payment_method=payment(payment_methods.current),
            available_payment_methods=[payment(method) for method in payment_methods.available],
            product_tier=ProductTierRead.from_tier(workspace.product_tier),
        )


class WorkspaceBillingSettingsUpdate(BaseModel):
    workspace_payment_method: Optional[PaymentMethod] = Field(
        default=None, description="The payment method selected for workspace"
    )
    product_tier: Optional[ProductTierRead] = Field(default=None, description="The product tier of this workspace")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "workspace_payment_method": {
                        "method": "aws_marketplace",
                        "subscription_id": "00000000-0000-0000-0000-000000000000",
                    },
                    "product_tier": "Free",
                }
            ]
        }
    }
