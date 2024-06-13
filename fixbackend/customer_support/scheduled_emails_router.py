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

from datetime import timedelta, datetime, timezone
from typing import Annotated, List

from fastapi import APIRouter, Form, Request, Response, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from fixbackend.dependencies import FixDependencies, ServiceNames
from fixbackend.domain_events.consumers import ScheduleTrialEndReminder, UnscheduleTrialEndReminder
from fixbackend.ids import WorkspaceId
from fixbackend.notification.email.one_time_email import OneTimeEmailKind
from fixbackend.workspaces.repository import WorkspaceRepositoryImpl


def scheduled_emails_router(dependencies: FixDependencies, templates: Jinja2Templates) -> APIRouter:

    router = APIRouter()

    workspace_repo = dependencies.service(ServiceNames.workspace_repo, WorkspaceRepositoryImpl)
    schedule_trial_end = dependencies.service(
        ServiceNames.schedule_trial_end_reminder_consumer, ScheduleTrialEndReminder
    )
    unschedule_trial_end = dependencies.service(
        ServiceNames.unschedule_trial_end_reminder_consumer, UnscheduleTrialEndReminder
    )

    @router.get("/", response_class=HTMLResponse, name="scheduled_emails:index")
    async def index(request: Request) -> Response:

        context = {
            "request": request,
            "email_kinds": [OneTimeEmailKind.TrialEndNotification],
        }

        return templates.TemplateResponse(request=request, name="scheduled_emails/index.html", context=context)

    @router.post("/schedule_trial_end", response_class=HTMLResponse, name="scheduled_emails:schedule_trial_end")
    async def schedule_trial_end_emails(
        request: Request,
        days_in_trial: Annotated[int, Form()],
        schedule_at: Annotated[datetime, Form()],
        email_kind: Annotated[OneTimeEmailKind, Form()],
    ) -> Response:

        schedule_at = schedule_at.replace(tzinfo=timezone.utc)

        affected_workspaces: List[WorkspaceId] = []

        workspaces = await workspace_repo.list_expired_trials(been_in_trial_tier_for=timedelta(days=days_in_trial))
        for workspace in workspaces:
            await schedule_trial_end.schedule_trial_end_reminder(workspace.id, schedule_at, kind=email_kind)
            affected_workspaces.append(workspace.id)

        return templates.TemplateResponse(
            request=request,
            name="scheduled_emails/scheduling_result.html",
            context={
                "workspace_ids": affected_workspaces,
                "email_kind": email_kind,
            },
        )

    @router.post("/unschedule_trial_end", response_class=HTMLResponse, name="scheduled_emails:unschedule_trial_end")
    async def unschedule_trial_end_emails(
        request: Request,
        workspace_ids: Annotated[List[WorkspaceId], Form()],
        email_kind: Annotated[OneTimeEmailKind, Form()],
    ) -> Response:

        for id in workspace_ids:
            await unschedule_trial_end.unschedule_trial_end_reminder(id, kind=email_kind)

        return Response(
            status_code=status.HTTP_201_CREATED,
            content="",
        )

    return router
