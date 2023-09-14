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

import os
import sys
from argparse import ArgumentParser, Namespace
from typing import Annotated, Optional

from fastapi import Depends
from pydantic_settings import BaseSettings


class Config(BaseSettings):
    instance_id: str
    database_name: str
    database_user: str
    database_password: Optional[str]
    database_host: str
    database_port: int
    secret: str
    google_oauth_client_id: str
    google_oauth_client_secret: str
    github_oauth_client_id: str
    github_oauth_client_secret: str
    redis_readwrite_url: str
    redis_readonly_url: str

    @property
    def database_url(self) -> str:
        password = f":{self.database_password}" if self.database_password else ""
        return f"mysql+aiomysql://{self.database_user}{password}@{self.database_host}:{self.database_port}/{self.database_name}"  # noqa


def parse_args() -> Namespace:
    parser = ArgumentParser(prog="FIX Backend")
    parser.add_argument(
        "--instance-id", help="Unique id of this instance in a cluster of fixbackend services", default="single"
    )
    parser.add_argument("--database-name", default=os.environ.get("FIX_DATABASE_NAME", "fix-database"))
    parser.add_argument("--database-user", default=os.environ.get("FIX_DATABASE_USER", "mariadb"))
    parser.add_argument("--database-password", default=os.environ.get("FIX_DATABASE_PASSWORD"))
    parser.add_argument("--database-host", default=os.environ.get("FIX_DATABASE_HOST", "localhost"))
    parser.add_argument("--database-port", type=int, default=int(os.environ.get("FIX_DATABASE_PORT", "3306")))
    parser.add_argument("--secret", default="secret")
    parser.add_argument("--google-oauth-client-id", default=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""))
    parser.add_argument("--google-oauth-client-secret", default=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""))
    parser.add_argument("--github-oauth-client-id", default=os.environ.get("GITHUB_OAUTH_CLIENT_ID", ""))
    parser.add_argument("--github-oauth-client-secret", default=os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", ""))
    parser.add_argument(
        "--redis-readwrite-url", default=os.environ.get("REDIS_READWRITE_URL", "redis://localhost:6379/0")
    )
    parser.add_argument(
        "--redis-readonly-url", default=os.environ.get("REDIS_READONLY_URL", "redis://localhost:6379/0")
    )
    parser.add_argument("--skip-migrations", default=False, action="store_true")
    args, _ = parser.parse_known_args(sys.argv[1:])
    return args


def get_config() -> Config:
    args = parse_args()
    delattr(args, "skip_migrations")  # this is not a valid config option
    return Config(**vars(args))


# placeholder for dependencies, will be replaced during the app initialization
def config() -> Config:
    raise RuntimeError("Config dependency not initialized yet.")


ConfigDependency = Annotated[Config, Depends(config)]
