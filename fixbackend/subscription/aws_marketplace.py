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
import logging
from datetime import timedelta
from typing import Optional
from uuid import uuid4

import boto3
from fixcloudutils.service import Service
from fixcloudutils.types import Json

from fixbackend.auth.models import User
from fixbackend.ids import PaymentMethodId
from fixbackend.sqs import SQSRawListener
from fixbackend.subscription.models import AwsMarketplaceSubscription, SubscriptionMethod
from fixbackend.subscription.subscription_repository import (
    SubscriptionRepository,
)
from fixbackend.workspaces.repository import WorkspaceRepository

log = logging.getLogger(__name__)


class AwsMarketplaceHandler(Service):
    def __init__(
        self,
        subscription_repo: SubscriptionRepository,
        workspace_repo: WorkspaceRepository,
        session: boto3.Session,
        sqs_queue_url: Optional[str],
    ) -> None:
        self.aws_marketplace_repo = subscription_repo
        self.workspace_repo = workspace_repo
        self.listener = (
            SQSRawListener(
                session,
                sqs_queue_url,
                self.handle_message,
                consider_failed_after=timedelta(minutes=5),
                max_nr_of_messages_in_one_batch=1,
                wait_for_new_messages_to_arrive=timedelta(seconds=5),
            )
            if sqs_queue_url is not None
            else None
        )
        self.marketplace_client = session.client("meteringmarketplace")

    async def start(self) -> None:
        if self.listener is not None:
            await self.listener.start()

    async def stop(self) -> None:
        if self.listener is not None:
            await self.listener.stop()

    async def subscribed(self, user: User, token: str) -> Optional[SubscriptionMethod]:
        log.info(f"AWS Marketplace subscription for user {user.email} with token {token}")
        # Get the related data from AWS. Will throw in case of an error.
        customer_data = self.marketplace_client.resolve_customer(RegistrationToken=token)
        log.debug(f"AWS Marketplace user {user.email} got customer data: {customer_data}")
        product_code = customer_data["ProductCode"]
        customer_identifier = customer_data["CustomerIdentifier"]
        customer_aws_account_id = customer_data["CustomerAWSAccountId"]

        # get all workspaces of the user and use the first one if it is the only one
        # if more than one workspace exists, the user needs to define the workspace in a later step
        workspaces = await self.workspace_repo.list_workspaces(user.id)
        workspace_id = workspaces[0].id if len(workspaces) == 1 else None

        # only create a new subscription if there is no existing one
        if existing := await self.aws_marketplace_repo.aws_marketplace_subscription(user.id, customer_identifier):
            log.debug(f"AWS Marketplace user {user.email}: return existing subscription")
            return existing
        else:
            subscription = AwsMarketplaceSubscription(
                id=PaymentMethodId(uuid4()),
                user_id=user.id,
                workspace_id=workspace_id,
                customer_identifier=customer_identifier,
                customer_aws_account_id=customer_aws_account_id,
                product_code=product_code,
                active=True,
            )
            return await self.aws_marketplace_repo.create(subscription)

    async def handle_message(self, message: Json) -> None:
        # See: https://docs.aws.amazon.com/marketplace/latest/userguide/saas-notification.html
        action = message["action"]
        log.info(f"AWS Marketplace. Received message: {message}")
        # customer_identifier = message["customer-identifier"]
        # free_trial = message.get("isFreeTrialTermPresent", False)
        match action:
            case "subscribe-success":
                # allow sending metering records
                pass
            case "subscribe-fail":
                # wait for subscribe-success
                pass
            case "unsubscribe-pending":
                # TODO: send metering records!
                pass
            case "unsubscribe-success":
                # the user has unsubscribed
                pass
            case _:
                raise ValueError(f"Unknown action: {action}")
