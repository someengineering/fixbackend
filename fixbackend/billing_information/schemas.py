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

from typing import List, Literal, Union
from fixbackend.billing_information.models import PaymentMethods, WorkspacePaymentMethods
from fixbackend.billing_information import models

from fixbackend.ids import BillingId, ProductTier, SubscriptionId, WorkspaceId
from fixbackend.subscription.models import BillingEntry
from enum import Enum

from fixbackend.workspaces.models import Workspace


class BillingEntryRead(BaseModel):
    id: BillingId = Field(description="Id of the billing entry")
    workspace_id: WorkspaceId = Field(description="The workspace's unique identifier")
    subscription_id: SubscriptionId = Field(description="The subscription's unique identifier")
    tier: ProductTier = Field(description="Product tier during the billing period")
    period_start: datetime = Field(description="The start of the billing period")
    period_end: datetime = Field(description="The end of the billing period")
    nr_of_accounts_charged: int = Field(description="The number of accounts charged during the billing period")

    @staticmethod
    def from_model(billing_entry: BillingEntry) -> "BillingEntryRead":
        return BillingEntryRead(
            id=billing_entry.id,
            workspace_id=billing_entry.workspace_id,
            subscription_id=billing_entry.subscription_id,
            tier=ProductTier(billing_entry.tier),
            period_start=billing_entry.period_start,
            period_end=billing_entry.period_end,
            nr_of_accounts_charged=billing_entry.nr_of_accounts_charged,
        )


class AwsSubscription(BaseModel):
    method: Literal["aws_marketplace"]
    subscription_id: SubscriptionId = Field(description="AWS Marketplace subscription identifier")


class NoPaymentMethod(BaseModel):
    method: Literal["none"]


PaymentMethod = Union[AwsSubscription, NoPaymentMethod]


class ProductTierRead(str, Enum):
    Free = "free"  # todo: change to "Free" once the FE is updated
    Plus = "Plus"
    Business = "Business"
    Enterprise = "Enterprise"

    def to_tier(self) -> ProductTier:
        match self:
            case ProductTierRead.Free:
                return ProductTier.Free
            case ProductTierRead.Plus:
                return ProductTier.Plus
            case ProductTierRead.Business:
                return ProductTier.Business
            case ProductTierRead.Enterprise:
                return ProductTier.Enterprise

    @staticmethod
    def from_tier(tier: ProductTier) -> "ProductTierRead":
        match tier:
            case ProductTier.Free:
                return ProductTierRead.Free
            case ProductTier.Plus:
                return ProductTierRead.Plus
            case ProductTier.Business:
                return ProductTierRead.Business
            case ProductTier.Enterprise:
                return ProductTierRead.Enterprise


class WorkspaceBillingSettingsRead(BaseModel):
    workspace_payment_method: PaymentMethod = Field(description="The payment method selected for workspace")
    available_payment_methods: List[PaymentMethod] = Field(description="The payment methods available for workspace")
    product_tier: ProductTierRead = Field(description="The product tier of this workspace")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "payment_method": "aws_marketplace",
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
    ) -> "WorkspaceBillingSettingsRead":

        def payment(payment_method: models.PaymentMethod) -> PaymentMethod:
            match payment_method:
                case PaymentMethods.AwsSubscription(subscription_id):
                    return AwsSubscription(method="aws_marketplace", subscription_id=subscription_id)
                case PaymentMethods.NoPaymentMethod():
                    return NoPaymentMethod(method="none")

        return WorkspaceBillingSettingsRead(
            workspace_payment_method=payment(payment_methods.current),
            available_payment_methods=[payment(method) for method in payment_methods.available],
            product_tier=ProductTierRead.from_tier(workspace.product_tier),
        )


class WorkspaceBillingSettingsUpdate(BaseModel):
    workspace_payment_method: PaymentMethod = Field(description="The payment method selected for workspace")
    product_tier: ProductTierRead = Field(description="The product tier of this workspace")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "payment_method": "aws_marketplace",
                    "workspace_payment_method": {
                        "method": "aws_marketplace",
                        "subscription_id": "00000000-0000-0000-0000-000000000000",
                    },
                    "product_tier": "Free",
                }
            ]
        }
    }
