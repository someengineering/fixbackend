from fastapi_users.authentication import AuthenticationBackend
from httpx_oauth.clients.github import GitHubOAuth2
from httpx_oauth.clients.google import GoogleOAuth2

from fixbackend.auth.jwt import get_jwt_strategy
from fixbackend.auth.redirect_to_spa import RedirectToSPA
from fixbackend.config import get_config

google_client = GoogleOAuth2(get_config().google_oauth_client_id, get_config().google_oauth_client_secret)

github_client = GitHubOAuth2(get_config().github_oauth_client_id, get_config().github_oauth_client_secret)

transport = RedirectToSPA(redirect_path="/")


# should only be used for setting up the token via localstorage to launch the SPA
oauth_redirect_backend = AuthenticationBackend(name="spa-redirect", transport=transport, get_strategy=get_jwt_strategy)
