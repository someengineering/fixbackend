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

from fastapi_users.authentication import AuthenticationBackend
from httpx_oauth.clients.github import GitHubOAuth2
from httpx_oauth.clients.google import GoogleOAuth2

from fixbackend.auth.jwt import get_jwt_strategy
from fixbackend.auth.redirect_to_spa import RedirectToSPA
from fixbackend.config import Config


def google_client(config: Config) -> GoogleOAuth2:
    return GoogleOAuth2(config.google_oauth_client_id, config.google_oauth_client_secret)


def github_client(config: Config) -> GitHubOAuth2:
    return GitHubOAuth2(config.github_oauth_client_id, config.github_oauth_client_secret)


transport = RedirectToSPA(redirect_path="/")


# should only be used for setting up the token via localstorage to launch the SPA
oauth_redirect_backend = AuthenticationBackend(name="spa-redirect", transport=transport, get_strategy=get_jwt_strategy)
