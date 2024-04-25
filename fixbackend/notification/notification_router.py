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
from datetime import timedelta
from textwrap import dedent
from typing import Annotated, Dict, Optional, List
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, Depends, Request, Response, Query, HTTPException, Body, status
from fastapi_users.jwt import decode_jwt, generate_jwt
from fixcloudutils.types import Json
from starlette.responses import RedirectResponse, JSONResponse

from fixbackend.auth.depedencies import AuthenticatedUser
from fixbackend.dependencies import FixDependencies, ServiceNames
from fixbackend.errors import NotAllowed
from fixbackend.ids import WorkspaceId, BenchmarkName, NotificationProvider, Email
from fixbackend.jwt import JwtServiceImpl
from fixbackend.logging_context import set_workspace_id, set_context
from fixbackend.notification.email.email_sender import EMAIL_UNSUBSCRIBE_AUDIENCE
from fixbackend.notification.model import WorkspaceAlert, AlertingSetting
from fixbackend.notification.notification_service import NotificationService
from fixbackend.notification.user_notification_repo import (
    UserNotificationSettingsRepositoryImpl,
)
from fixbackend.permissions.models import WorkspacePermissions
from fixbackend.permissions.permission_checker import WorkspacePermissionChecker

log = logging.getLogger(__name__)
AddSlack = "notification_add_slack"
AddDiscord = "notification_add_discord"


STATE_TOKEN_AUDIENCE = "fix:notification-state"


def notification_router(fix: FixDependencies) -> APIRouter:
    router = APIRouter()
    cfg = fix.config

    def generate_state_token(data: Dict[str, str]) -> str:
        data["aud"] = STATE_TOKEN_AUDIENCE
        return generate_jwt(data, fix.config.secret, int(timedelta(minutes=30).total_seconds()))

    @router.get("/{workspace_id}/notifications")
    async def notifications(
        workspace_id: WorkspaceId,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.read_settings))],
    ) -> Dict[str, Json]:
        set_workspace_id(workspace_id)
        return await fix.service(
            ServiceNames.notification_service, NotificationService
        ).list_notification_provider_configs(workspace_id)

    @router.get("/notification/add/slack/confirm", name=AddSlack, include_in_schema=False, response_model=None)
    async def add_slack_confirm(
        request: Request,
        code: Optional[str] = Query(default=None),
        state: Optional[str] = Query(default=None),
        error: Optional[str] = Query(default=None),
        error_description: Optional[str] = Query(default=None),
    ) -> Response:
        error_redirect = RedirectResponse("/workspace-settings?message=slack_added&outcome=error")
        if error is not None:
            log.info(f"Add slack oauth confirmation: received error: {error}. description: {error_description}")
            return error_redirect
        if state is None or code is None:
            log.info(f"Add slack oauth confirmation: received no state or code: {state}, {code}")
            return error_redirect
        # if the state is not the same as the one we sent, it means that the user did not come from our page
        try:
            decoded_state = decode_jwt(state, fix.config.secret, [STATE_TOKEN_AUDIENCE])
        except (jwt.ExpiredSignatureError, jwt.DecodeError) as ex:
            log.info(f"OAuth callback: invalid state token: {state}, {ex}")
            return error_redirect

        if not (workspace_id := decoded_state.get("workspace_id")):
            log.info(f"OAuth callback: invalid workspace_id in state token: {decoded_state.get('workspace_id')}")
            return error_redirect

        workspace_id = WorkspaceId(workspace_id)

        set_workspace_id(workspace_id)
        # with our client and secret, we authorize the request to get an access token
        data: Json = dict(
            client_id=cfg.slack_oauth_client_id,
            client_secret=cfg.slack_oauth_client_secret,
            code=code,
            grant_type="authorization_code",
            redirect_uri=str(request.url_for(AddSlack, workspace_id=workspace_id)),
        )
        log.debug("Slack confirm: send this data to oauth.v2.access: %s", data)
        try:
            response = await fix.http_client.post("https://slack.com/api/oauth.v2.access", data=data)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return RedirectResponse(f"/workspace-settings?message=slack_added&outcome=error#{workspace_id}")
        if not data.get("ok"):
            return RedirectResponse(f"/workspace-settings?message=slack_added&outcome=error#{workspace_id}")

        # The data received has this structure:
        # { "ok": true,
        #   "app_id": "xxx",
        #   "authed_user": { "id": "xxx" },
        #   "scope": "incoming-webhook",
        #   "token_type": "bot",
        #   "access_token": "xxx",
        #   "bot_user_id": "xxx",
        #   "team": { "id": "xxx", "name": "xxx" },
        #   "enterprise": null,
        #   "is_enterprise_install": false,
        #   "incoming_webhook": {
        #     "channel": "#name",
        #     "channel_id": "xxx",
        #     "configuration_url": "https://fix.slack.com/services/xxxx",
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
        await ns.update_notification_provider_config(workspace_id, NotificationProvider.slack, hook["channel"], config)
        log.info("Slack webhook added successfully")
        return RedirectResponse(f"/workspace-settings?message=slack_added&outcome=success#{workspace_id}")

    @router.get("/{workspace_id}/notification/add/slack")
    async def add_slack(
        user: AuthenticatedUser,
        workspace_id: WorkspaceId,
        request: Request,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.read_settings))],
    ) -> Response:
        set_context(workspace_id=workspace_id, user_id=user.id)
        log.info(f"User {user.id} in workspace {workspace_id} wants to integrate slack notifications")
        data = {
            "workspace_id": str(workspace_id),
        }
        state = generate_state_token(data)
        params = dict(
            client_id=cfg.slack_oauth_client_id,
            response_type="code",
            scope="incoming-webhook",
            state=state,
            redirect_uri=str(request.url_for(AddSlack)),
        )
        log.debug("Add slack called with params: %s", params)
        return RedirectResponse("https://slack.com/oauth/v2/authorize?" + urlencode(params))

    @router.get("/notification/add/discord/confirm", name=AddDiscord, include_in_schema=False, response_model=None)
    async def add_discord_confirm(
        request: Request,
        code: Optional[str] = Query(default=None),
        state: Optional[str] = Query(default=None),
        error: Optional[str] = Query(default=None),
        error_description: Optional[str] = Query(default=None),
    ) -> Response:

        error_response = RedirectResponse("/workspace-settings?message=discord_added&outcome=error")
        if error is not None:
            log.info(f"Add discord oauth confirmation: received error: {error}. description: {error_description}")
            return error_response
        if state is None or code is None:
            log.info(f"Add discord oauth confirmation: received no state or code: {state}, {code}")
            return error_response

        # if the state is not the same as the one we sent, it means that the user did not come from our page
        try:
            state_obj = decode_jwt(state, fix.config.secret, [STATE_TOKEN_AUDIENCE])
        except (jwt.ExpiredSignatureError, jwt.DecodeError) as ex:
            log.info(f"Add discord oauth confirmation: received Invalid state: {state}", ex)
            return error_response

        workspace_id = WorkspaceId(state_obj["workspace_id"])
        set_workspace_id(workspace_id)

        # with our client and secret, we authorize the request to get an access token
        data: Json = dict(
            client_id=cfg.discord_oauth_client_id,
            client_secret=cfg.discord_oauth_client_secret,
            code=code,
            grant_type="authorization_code",
            redirect_uri=str(request.url_for(AddDiscord)),
        )
        response = await fix.http_client.post("https://discord.com/api/oauth2/token", data=data)
        try:
            response.raise_for_status()
            data = response.json()
            hook = data["webhook"]
        except Exception as ex:
            log.info(f"Could not add discord webhook: {ex}")
            return RedirectResponse(f"/workspace-settings?message=discord_added&outcome=error#{workspace_id}")

        config = dict(webhook_url=hook["url"])
        # store token and webhook url
        ns = fix.service(ServiceNames.notification_service, NotificationService)
        await ns.update_notification_provider_config(workspace_id, NotificationProvider.discord, "alert", config)

        # redirect to the UI
        log.info("Discord webhook added successfully")
        return RedirectResponse(f"/workspace-settings?message=discord_added&outcome=success#{workspace_id}")

    @router.get("/{workspace_id}/notification/add/discord")
    async def add_discord(
        user: AuthenticatedUser,
        workspace_id: WorkspaceId,
        request: Request,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update_settings))],
    ) -> Response:
        set_context(workspace_id=workspace_id, user_id=user.id)
        log.info("Add discord notifications requested.")
        data = {
            "workspace_id": str(workspace_id),
        }
        state = generate_state_token(data)
        params = dict(
            client_id=cfg.discord_oauth_client_id,
            response_type="code",
            scope="webhook.incoming",
            state=state,
            redirect_uri=str(request.url_for(AddDiscord)),
            workspace_id=str(workspace_id),
        )
        return RedirectResponse("https://discord.com/api/oauth2/authorize?" + urlencode(params))

    @router.put("/{workspace_id}/notification/add/pagerduty")
    async def add_pagerduty(
        user: AuthenticatedUser,
        workspace_id: WorkspaceId,
        name: Annotated[str, Query()],
        integration_key: Annotated[str, Query()],
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update_settings))],
    ) -> Response:
        set_context(workspace_id=workspace_id, user_id=user.id)
        if not name or not integration_key:
            raise HTTPException(status_code=400, detail="Missing integration key")
        config = dict(integration_key=integration_key)
        # store token and webhook url
        ns = fix.service(ServiceNames.notification_service, NotificationService)
        await ns.update_notification_provider_config(workspace_id, NotificationProvider.pagerduty, name, config)
        log.info("Pagerduty integration added successfully")
        return Response(status_code=204)

    @router.put("/{workspace_id}/notification/add/opsgenie")
    async def add_opsgenie(
        user: AuthenticatedUser,
        workspace_id: WorkspaceId,
        name: Annotated[str, Query()],
        api_key: Annotated[str, Query()],
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update_settings))],
    ) -> Response:
        set_context(workspace_id=workspace_id, user_id=user.id)
        if not name or not api_key:
            raise HTTPException(status_code=400, detail="Missing api key")
        config = dict(api_key=api_key)
        # store token and webhook url
        ns = fix.service(ServiceNames.notification_service, NotificationService)
        await ns.update_notification_provider_config(workspace_id, NotificationProvider.opsgenie, name, config)
        log.info("Opsgenie integration added successfully")
        return Response(status_code=204)

    @router.put("/{workspace_id}/notification/add/teams")
    async def add_teams(
        user: AuthenticatedUser,
        workspace_id: WorkspaceId,
        name: Annotated[str, Query()],
        webhook_url: Annotated[str, Query()],
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update_settings))],
    ) -> Response:
        set_context(workspace_id=workspace_id, user_id=user.id)
        if not name or not webhook_url:
            raise HTTPException(status_code=400, detail="Missing name or webhook URL")
        config = dict(webhook_url=webhook_url)
        # store token and webhook url
        ns = fix.service(ServiceNames.notification_service, NotificationService)
        await ns.update_notification_provider_config(workspace_id, NotificationProvider.teams, name, config)
        log.info("Pagerduty integration added successfully")
        return Response(status_code=204)

    @router.put("/{workspace_id}/notification/add/email")
    async def add_email(
        user: AuthenticatedUser,
        workspace_id: WorkspaceId,
        name: Annotated[str, Query()],
        email: Annotated[List[str], Query()],
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update_settings))],
    ) -> Response:
        set_context(workspace_id=workspace_id, user_id=user.id)
        if not name or not email:
            raise HTTPException(status_code=400, detail="Missing name or email address")
        config = dict(email=email)
        # store token and webhook url
        ns = fix.service(ServiceNames.notification_service, NotificationService)
        await ns.update_notification_provider_config(workspace_id, NotificationProvider.email, name, config)
        log.info("Email integration added successfully")
        return Response(status_code=204)

    @router.get("/{workspace_id}/alerting/setting")
    async def alerting_for(user: AuthenticatedUser, workspace_id: WorkspaceId) -> Dict[BenchmarkName, AlertingSetting]:
        set_context(workspace_id=workspace_id, user_id=user.id)
        ns = fix.service(ServiceNames.notification_service, NotificationService)
        return setting.alerts if (setting := await ns.alerting_for(workspace_id)) else {}

    @router.put("/{workspace_id}/alerting/setting")
    async def update_alerting_for(
        user: AuthenticatedUser,
        workspace_id: WorkspaceId,
        setting: Annotated[Dict[BenchmarkName, AlertingSetting], Body()],
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update_settings))],
    ) -> Response:
        set_context(workspace_id=workspace_id, user_id=user.id)
        try:
            ns = fix.service(ServiceNames.notification_service, NotificationService)
            await ns.update_alerting_for(WorkspaceAlert(workspace_id=workspace_id, alerts=setting))
            return Response(status_code=204)
        except ValueError as ex:
            return JSONResponse(status_code=422, content=dict(error=str(ex)))

    @router.delete("/{workspace_id}/notification/{channel}")
    async def delete_channel(
        workspace_id: WorkspaceId,
        channel: NotificationProvider,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update_settings))],
    ) -> Response:
        set_workspace_id(workspace_id=workspace_id)
        ns = fix.service(ServiceNames.notification_service, NotificationService)
        await ns.delete_notification_provider_config(workspace_id, channel)
        return Response(status_code=204)

    @router.post("/{workspace_id}/notification/{channel}/test")
    async def send_test_alert(
        workspace_id: WorkspaceId,
        channel: NotificationProvider,
        _: Annotated[bool, Depends(WorkspacePermissionChecker(WorkspacePermissions.update_settings))],
    ) -> Response:
        set_workspace_id(workspace_id=workspace_id)
        ns = fix.service(ServiceNames.notification_service, NotificationService)
        await ns.send_test_alert(workspace_id, channel)
        return Response(status_code=204)

    return router


def unsubscribe_router(fix: FixDependencies) -> APIRouter:
    router = APIRouter()

    @router.get("/unsubscribe", include_in_schema=False)
    async def unsubscribe(token: str) -> Response:

        decoded = await fix.service(ServiceNames.jwt_service, JwtServiceImpl).decode(
            token, [EMAIL_UNSUBSCRIBE_AUDIENCE]
        )
        if not decoded:
            log.info("invalid token")
            raise NotAllowed("Invalid token")
        email = decoded.get("sub")
        if not email:
            log.info("no email in token")
            raise NotAllowed("Invalid token")
        kind = decoded.get("kind")
        if not kind:
            log.info("no kind in token")
            raise NotAllowed("Invalid token")
        pref_service = fix.service(
            ServiceNames.user_notification_settings_repository, UserNotificationSettingsRepositoryImpl
        )
        await pref_service.update_notification_settings(Email(email), **{kind: False})
        content = dedent(
            f"""
            <!DOCTYPE html>
            <html>
            <body>

            <h1>You've successfully unsubscribed from {kind} emails</h1>

            </body>
            </html>
            """
        )
        response = Response(content=content, media_type="text/html", status_code=status.HTTP_200_OK)
        return response

    return router
