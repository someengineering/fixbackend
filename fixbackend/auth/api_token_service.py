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
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
from fixcloudutils.asyncio.process_pool import AsyncProcessPool
from fixcloudutils.util import utc
from sqlalchemy.exc import IntegrityError
from typing import Optional, Tuple, List
from uuid import UUID

from fastapi_users.password import PasswordHelperProtocol
from fixcloudutils.service import Service
from passlib.pwd import genword
from sqlalchemy import delete, select

from fixbackend.auth.auth_backend import FixJWTStrategy
from fixbackend.auth.models import ApiToken, User
from fixbackend.auth.models.orm import ApiToken as ApiTokenEntity
from fixbackend.auth.user_repository import UserRepository
from fixbackend.errors import NotAllowed
from fixbackend.ids import WorkspaceId
from fixbackend.permissions.models import all_permissions
from fixbackend.types import AsyncSessionMaker
from fixbackend.utils import uid
from fixbackend.workspaces.repository import WorkspaceRepository


class ApiTokenService(Service):

    def __init__(
        self,
        session_maker: AsyncSessionMaker,
        jwt_strategy: FixJWTStrategy,
        user_repo: UserRepository,
        password_helper: PasswordHelperProtocol,
        workspace_repo: WorkspaceRepository,
        process_pool: AsyncProcessPool,
    ) -> None:
        self.session_maker = session_maker
        self.jwt_strategy = jwt_strategy
        self.user_repo = user_repo
        self.password_helper = password_helper
        self.workspace_repo = workspace_repo
        self.process_pool = process_pool

    async def login(self, api_token: str) -> str:
        tkn = await self._get_user_token(api_token, update_last_used=True)
        user = await self.user_repo.get(tkn.user_id)
        assert user, "User not found"
        permission = tkn.permission or all_permissions
        workspace = tkn.workspace_id
        permissions = {
            role.workspace_id: role.permissions().value & permission
            for role in user.roles
            if workspace is None or workspace == role.workspace_id
        }
        return self.jwt_strategy.create_token(str(user.id), "api_token", permissions)

    async def create_token(
        self, user: User, name: str, permission: Optional[int] = None, workspace_id: Optional[WorkspaceId] = None
    ) -> Tuple[ApiToken, str]:
        try:
            token_id, token = self._create_token()
            token_hash = self.password_helper.hash(token)
            if workspace_id:
                ids = {ws.id for ws in await self.workspace_repo.list_workspaces(user)}
                assert workspace_id in ids, "User is not a member of the workspace"
            async with self.session_maker() as session:
                now = utc()
                entity = ApiTokenEntity(
                    id=token_id,
                    name=name,
                    hash=token_hash,
                    user_id=user.id,
                    workspace_id=workspace_id,
                    permission=permission,
                    created_at=now,
                    updated_at=now,
                )
                session.add(entity)
                result = entity.to_model()
                await session.commit()
            return result, token
        except IntegrityError:
            raise AssertionError("Token name already exists")

    async def token_info(
        self, user: User, *, api_token_name: Optional[str] = None, api_token: Optional[str] = None
    ) -> Optional[ApiToken]:
        if api_token:
            result = await self._get_user_token(api_token, update_last_used=False)
            return result if result.user_id == user.id else None
        elif api_token_name:
            async with self.session_maker() as session:
                cursor = await session.execute(
                    select(ApiTokenEntity)
                    .where(ApiTokenEntity.name == api_token_name)
                    .where(ApiTokenEntity.user_id == user.id)
                )
                tkn = cursor.scalars().one_or_none()
                return tkn.to_model() if tkn else None
        else:
            return None

    async def delete_token(
        self, user: User, *, api_token_name: Optional[str] = None, api_token: Optional[str] = None
    ) -> None:
        if info := await self.token_info(user, api_token_name=api_token_name, api_token=api_token):
            async with self.session_maker() as session:
                await session.execute(delete(ApiTokenEntity).where(ApiTokenEntity.id == info.id))
                await session.commit()

    async def list_tokens(self, user: User) -> List[ApiToken]:
        async with self.session_maker() as session:
            rows = await session.execute(select(ApiTokenEntity).where(ApiTokenEntity.user_id == user.id))
            return [row.to_model() for row in rows.scalars()]

    async def _get_user_token(self, api_token: str, update_last_used: bool) -> ApiToken:
        if len(api_token) != 68 or not api_token.startswith("fix_"):
            raise NotAllowed("Invalid token")
        token_id = UUID(api_token[4:36])
        async with self.session_maker() as session:
            if (
                row := (await session.execute(select(ApiTokenEntity).where(ApiTokenEntity.id == token_id)))
                .scalars()
                .one_or_none()
            ):
                verified, updated_password_hash = await self.process_pool.submit(
                    self.password_helper.verify_and_update, api_token, row.hash
                )
                if not verified:
                    raise NotAllowed("Invalid token")
                # Update password hash to a more robust one if needed
                if updated_password_hash:
                    row.hash = updated_password_hash
                if update_last_used:
                    row.last_used_at = utc()
                result = row.to_model()
                await session.commit()
                return result
        raise NotAllowed("Invalid token")

    def _create_token(self) -> Tuple[UUID, str]:
        token_id = uid()
        password = genword(entropy="secure", length=32, charset="hex")
        return token_id, f'fix_{str(token_id).replace("-", "")}{password}'
