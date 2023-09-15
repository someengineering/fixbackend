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

from typing import Iterator
import pytest
import asyncio
from asyncio import AbstractEventLoop

from fixbackend.config import Config


@pytest.fixture(scope="session")
def event_loop() -> Iterator[AbstractEventLoop]:
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def default_config() -> Config:
    return Config(
        instance_id="",
        database_name="",
        database_user="",
        database_password=None,
        database_host="",
        database_port=3306,
        secret="",
        google_oauth_client_id="",
        google_oauth_client_secret="",
        github_oauth_client_id="",
        github_oauth_client_secret="",
        redis_readwrite_url="",
        redis_readonly_url="",
    )
