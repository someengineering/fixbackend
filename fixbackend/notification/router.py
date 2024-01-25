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
import json
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Response, Query, HTTPException
from fixcloudutils.types import Json
from starlette.responses import RedirectResponse

from fixbackend.auth.depedencies import AuthenticatedUser
from fixbackend.dependencies import FixDependencies, ServiceNames
from fixbackend.ids import WorkspaceId
from fixbackend.notification.service import NotificationService

log = logging.getLogger(__name__)
AddSlack = "notification_add_slack"
AddDiscord = "notification_add_discord"

State = "add-notification-channel"


def notification_router(fix: FixDependencies) -> APIRouter:
    router = APIRouter()
    cfg = fix.config

    @router.get(
        "/{workspace_id}/notification/add/slack/confirm", name=AddSlack, include_in_schema=False, response_model=None
    )
    async def add_slack_confirm(
        workspace_id: WorkspaceId, request: Request, code: str = Query(), state: str = Query()
    ) -> Response:
        # if state is not the same as the one we sent, it means that the user did not come from our page
        if state != State:
            return Response("Invalid state", status_code=400)

        # with our client and secret we authorize the request to get an access token
        data: Json = dict(
            client_id=cfg.slack_oauth_client_id,
            client_secret=cfg.slack_oauth_client_secret,
            code=code,
            grant_type="authorization_code",
            redirect_uri=str(request.url_for(AddSlack, workspace_id=workspace_id)),
        )
        log.debug("Slack confirm: send this data to oauth.v2.access: %s", data)
        response = await fix.http_client.post("https://slack.com/api/oauth.v2.access", data=data)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise HTTPException(status_code=400, detail=data.get("error"))

        # The data received has this structure:
        # { "ok": true,
        #   "app_id": "xxxxxxx",
        #   "authed_user": { "id": "xxxxxx" },
        #   "scope": "incoming-webhook",
        #   "token_type": "bot",
        #   "access_token": "xxxxxxx",
        #   "bot_user_id": "xxxxxxx",
        #   "team": { "id": "xxxxxx", "name": "xxxxxx" },
        #   "enterprise": null,
        #   "is_enterprise_install": false,
        #   "incoming_webhook": {
        #     "channel": "#name",
        #     "channel_id": "xxxxx",
        #     "configuration_url": "https://resoto.slack.com/services/xxxx",
        #     "url": "https://hooks.slack.com/services/xxxx/xxxx"
        # }}
        log.debug("Slack confirm: got this data from oauth.v2.access: %s", data)
        hook: Json = data["incoming_webhook"]
        config = dict(
            access_token=data["access_token"],
            webhook_url=hook["url"],
            channel=hook["channel"],
        )
        ns = fix.service(ServiceNames.notification_service, NotificationService)
        await ns.update_notification_provider_config(workspace_id, "slack", hook["channel"], config)

        # redirect to the UI: TODO: where exactly?
        return RedirectResponse("/?message=slack_channel_added")

    @router.get("/{workspace_id}/notification/add/slack")
    async def add_slack(user: AuthenticatedUser, workspace_id: WorkspaceId, request: Request) -> Response:
        log.info(f"User {user.id} in workspace {workspace_id} wants to integrate slack notifications")
        params = dict(
            client_id=cfg.slack_oauth_client_id,
            response_type="code",
            scope="incoming-webhook",
            state=State,
            redirect_uri=str(request.url_for(AddSlack, workspace_id=workspace_id)),
        )
        log.debug("Add slack called with params: %s", params)
        return RedirectResponse("https://slack.com/oauth/v2/authorize?" + urlencode(params))

    @router.get("/notification/add/discord/confirm", name=AddDiscord, include_in_schema=False, response_model=None)
    async def add_discord_confirm(request: Request, code: str = Query(), state: str = Query()) -> Response:
        state_obj = json.loads(state)
        # if state is not the same as the one we sent, it means that the user did not come from our page
        if state_obj.get("state") != State or not isinstance(state_obj.get("workspace_id"), str):
            log.error(f"Received Invalid state: {state_obj}")
            return Response("Invalid state", status_code=400)
        workspace_id = WorkspaceId(state_obj["workspace_id"])

        # with our client and secret we authorize the request to get an access token
        data = dict(
            client_id=cfg.discord_oauth_client_id,
            client_secret=cfg.discord_oauth_client_secret,
            code=code,
            grant_type="authorization_code",
            redirect_uri=str(request.url_for(AddDiscord)),
        )
        response = await fix.http_client.post("https://discord.com/api/oauth2/token", data=data)
        response.raise_for_status()
        data = response.json()
        hook = data["webhook"]

        config = dict(webhook_url=hook["url"])
        # store token and webhook url
        ns = fix.service(ServiceNames.notification_service, NotificationService)
        await ns.update_notification_provider_config(workspace_id, "discord", "alert", config)

        # redirect to the UI
        return RedirectResponse("/?message=discord")

    @router.get("/{workspace_id}/notification/add/discord")
    async def add_discord(_: AuthenticatedUser, workspace_id: WorkspaceId, request: Request) -> Response:
        params = dict(
            client_id=cfg.discord_oauth_client_id,
            response_type="code",
            scope="webhook.incoming",
            state=json.dumps(dict(state=State, workspace_id=str(workspace_id))),
            redirect_uri=str(request.url_for(AddDiscord)),
            workspace_id=str(workspace_id),
        )
        return RedirectResponse("https://discord.com/api/oauth2/authorize?" + urlencode(params))

    @router.put("/{workspace_id}/notification/add/pagerduty")
    async def add_pagerduty(
        _: AuthenticatedUser, workspace_id: WorkspaceId, name: str = Query(), integration_key: str = Query()
    ) -> None:
        if not name or not integration_key:
            raise HTTPException(status_code=400, detail="Missing integration key")
        config = dict(integration_key=integration_key)
        # store token and webhook url
        ns = fix.service(ServiceNames.notification_service, NotificationService)
        await ns.update_notification_provider_config(workspace_id, "pagerduty", name, config)

    @router.put("/{workspace_id}/notification/add/pagerduty")
    async def add_teams(
        _: AuthenticatedUser, workspace_id: WorkspaceId, name: str = Query(), webhook_url: str = Query()
    ) -> None:
        if not name or not webhook_url:
            raise HTTPException(status_code=400, detail="Missing integration key")
        config = dict(webhook_url=webhook_url)
        # store token and webhook url
        ns = fix.service(ServiceNames.notification_service, NotificationService)
        await ns.update_notification_provider_config(workspace_id, "teams", name, config)

    return router
