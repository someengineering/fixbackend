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

from typing import AsyncGenerator, Annotated, Callable

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fixbackend.dependencies import FixDependency

AsyncSessionMaker = Callable[[], AsyncSession]


async def get_async_session_maker(fix: FixDependency) -> AsyncSessionMaker:
    return async_sessionmaker(fix.async_engine)


AsyncSessionMakerDependency = Annotated[AsyncSessionMaker, Depends(get_async_session_maker)]


async def get_async_session(maker: AsyncSessionMakerDependency) -> AsyncGenerator[AsyncSession, None]:
    async with maker() as session:
        yield session


AsyncSessionDependency = Annotated[AsyncSession, Depends(get_async_session, use_cache=False)]
