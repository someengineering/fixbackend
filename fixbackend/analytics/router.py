#  Copyright (c) 2024. Some Engineering
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
from base64 import b64decode

from fastapi import APIRouter, Response
from fixcloudutils.util import utc, uuid_str

from fixbackend.analytics import AnalyticsEventSender
from fixbackend.analytics.events import AEEmailOpened
from fixbackend.dependencies import FixDependencies, ServiceNames
from fixbackend.ids import UserId


# 1x1 transparent PNG pixel
pxl_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg=="
log = logging.getLogger(__name__)


def analytics_router(dependencies: FixDependencies) -> APIRouter:
    router = APIRouter()

    @router.get("/analytics/email_opened/pixel", include_in_schema=False)
    async def email_opened(user: UserId, email: str) -> Response:
        log.info(f"Email opened by {user} for email {email}")
        sender = dependencies.service(ServiceNames.analytics_event_sender, AnalyticsEventSender)  # type: ignore
        await sender.send(AEEmailOpened(id=uuid_str(), created_at=utc(), user_id=user, email=email))
        return Response(content=b64decode(pxl_base64), media_type="image/png")

    return router
