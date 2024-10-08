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
import logging

from fastapi.routing import APIRouter
from fixcloudutils.util import utc
from starlette.responses import Response

from fixbackend.auth.depedencies import AuthenticatedUser, fastapi_users
from fixbackend.auth.schemas import UserNotificationSettingsRead, UserRead, UserUpdate, UserNotificationSettingsWrite
from fixbackend.auth.user_repository import UserRepository
from fixbackend.dependencies import FixDependencies, ServiceNames

from fixbackend.notification.user_notification_repo import UserNotificationSettingsRepositoryDependency

log = logging.getLogger(__name__)


def users_router(dependencies: FixDependencies) -> APIRouter:
    router = APIRouter()

    router.include_router(fastapi_users.get_users_router(UserRead, UserUpdate))

    @router.get("/me/settings/notifications")
    async def get_user_notification_settings(
        user: AuthenticatedUser,
        user_notification_repo: UserNotificationSettingsRepositoryDependency,
    ) -> UserNotificationSettingsRead:
        settings = await user_notification_repo.get_notification_settings(user.id)
        return UserNotificationSettingsRead.from_model(settings)

    @router.put("/me/settings/notifications")
    async def update_user_notification_settings(
        user: AuthenticatedUser,
        notification_settings: UserNotificationSettingsWrite,
        user_notification_repo: UserNotificationSettingsRepositoryDependency,
    ) -> UserNotificationSettingsRead:
        updated = await user_notification_repo.update_notification_settings(
            user.id, **notification_settings.model_dump()
        )
        return UserNotificationSettingsRead.from_model(updated)

    @router.post("/me/active")
    async def signal_active(user: AuthenticatedUser) -> Response:
        log.info(f"User {user.id} send an active signal")
        await dependencies.service(ServiceNames.user_repo, UserRepository).update_partial(user.id, last_active=utc())
        return Response(status_code=204)

    return router
