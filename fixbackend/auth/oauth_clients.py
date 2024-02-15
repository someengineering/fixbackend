from typing import Any, Dict, List, Optional, Tuple, cast
from httpx_oauth.clients.github import GitHubOAuth2, BASE_SCOPES, PROFILE_ENDPOINT, EMAILS_ENDPOINT
import httpx
from httpx_oauth.errors import GetIdEmailError


class GithubOauthClient(GitHubOAuth2):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        scopes: Optional[List[str]] = BASE_SCOPES,
        name: str = "github",
    ):
        super().__init__(
            client_id,
            client_secret,
            scopes,
            name,
        )

    async def get_id_email_username(self, token: str) -> Tuple[str, Optional[str], Optional[str]]:  # pragma: no cover
        async with httpx.AsyncClient(headers={**self.request_headers, "Authorization": f"token {token}"}) as client:
            response = await client.get(PROFILE_ENDPOINT)

            if response.status_code >= 400:
                raise GetIdEmailError(response.json())

            data = cast(Dict[str, Any], response.json())

            id = data["id"]
            email = data.get("email")

            # No public email, make a separate call to /user/emails
            if email is None:
                response = await client.get(EMAILS_ENDPOINT)

                if response.status_code >= 400:
                    raise GetIdEmailError(response.json())

                emails = cast(List[Dict[str, Any]], response.json())

                email = emails[0]["email"]

            return str(id), email, data.get("login")
