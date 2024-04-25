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

# The list of all models in the project
# This is used by alembic to generate migrations
#
# If you add a new model, you need to add it here,
# otherwise alembic won't be able to detect it

from fixbackend.auth.models.orm import User, OAuthAccount  # noqa
from fixbackend.workspaces.models.orm import Organization, OrganizationInvite  # noqa
from fixbackend.graph_db.service import GraphDatabaseAccessEntity  # noqa
from fixbackend.cloud_accounts.models.orm import CloudAccount  # noqa
from fixbackend.dispatcher.next_run_repository import NextTenantRun  # noqa
from fixbackend.metering.metering_repository import MeteringRecordEntity  # noqa
from fixbackend.keyvalue.json_kv import JsonEntry  # noqa
from fixbackend.subscription.subscription_repository import SubscriptionEntity, BillingEntity  # noqa
from fixbackend.notification.workspace_alert_config_repo import WorkspaceAlertConfigEntry  # noqa
from fixbackend.notification.notification_provider_config_repo import NotificationProviderConfigEntity  # noqa
from fixbackend.notification.user_notification_repo import UserNotificationSettingsEntity  # noqa
from fixbackend.permissions.role_repository import UserRoleAssignmentEntity  # noqa
from fixbackend.notification.email.scheduled_email import ScheduledEmailEntity, ScheduledEmailSentEntity  # noqa
from fixbackend.notification.email.one_time_email import OneTimeEmailEntity  # noqa
