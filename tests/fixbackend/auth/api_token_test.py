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
import re

from fixcloudutils.util import utc
from pytest import raises
from fixbackend.auth.api_token_service import ApiTokenService
from fixbackend.auth.auth_backend import FixJWTStrategy
from fixbackend.auth.models import User, ApiToken
from fixbackend.auth.schemas import ApiTokenDetails
from fixbackend.errors import NotAllowed
from fixbackend.ids import WorkspaceId, UserId
from fixbackend.utils import uid
from fixbackend.workspaces.models import Workspace


async def test_token_crud(
    api_token_service: ApiTokenService, user: User, workspace: Workspace, jwt_strategy: FixJWTStrategy
) -> None:
    # create a token
    token, tk_str = await api_token_service.create_token(user, "test")
    assert token.id is not None
    assert len(tk_str) > 64
    assert tk_str.startswith("fix_")

    # it is possible to create an access token
    jwt = await api_token_service.login(tk_str)
    values = await jwt_strategy.decode_token(jwt)
    assert values is not None
    assert values["sub"] == str(user.id)
    assert values["token_origin"] == "api_token"

    # list all tokens
    tokens = await api_token_service.list_tokens(user)
    assert len(tokens) == 1
    assert tokens[0].last_used_at is not None  # the token was used to log in

    # only allows access wit a valid token
    with raises(NotAllowed):
        await api_token_service.login(re.sub(r"a", "b", tk_str))

    # create a token with workspace and permission
    token2, tk2_str = await api_token_service.create_token(user, "foo", 1, workspace.id)

    # only workspaces that belong to the user can be used
    with raises(AssertionError):
        await api_token_service.create_token(user, "bla", 1, WorkspaceId(uid()))

    assert len(await api_token_service.list_tokens(user)) == 2
    # delete the token by name
    await api_token_service.delete_token(user, api_token_name=token.name)
    # delete the token by token string
    await api_token_service.delete_token(user, api_token=tk2_str)
    assert len(await api_token_service.list_tokens(user)) == 0

    # the same user cannot create a token with the same name
    await api_token_service.create_token(user, "batman")
    with raises(AssertionError):
        await api_token_service.create_token(user, "batman")


async def test_conversion() -> None:
    now = utc()
    token = ApiToken(uid(), "foo", "bar", UserId(uid()), WorkspaceId(uid()), 123, now, now, now)
    details = ApiTokenDetails.from_token(token)
    for prop in ApiTokenDetails.__annotations__.keys():  # all props are defined
        assert getattr(details, prop) is not None
