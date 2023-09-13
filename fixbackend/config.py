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
from typing import Annotated

from fastapi import Depends
from pydantic_settings import BaseSettings


class Config(BaseSettings):
    instance_id: str
    database_url: str
    secret: str
    google_oauth_client_id: str
    google_oauth_client_secret: str
    github_oauth_client_id: str
    github_oauth_client_secret: str
    redis_url: str


def parse_args() -> Namespace:
    parser = ArgumentParser(prog="FIX Backend")
    parser.add_argument(
        "--instance-id", help="Unique id of this instance in a cluster of fixbackend services", default="single"
    )
    parser.add_argument("--database-url", default="mysql+aiomysql://mariadb:mariadb@127.0.0.1:3306/mariadb")
    parser.add_argument("--secret", default="secret")
    parser.add_argument("--google-oauth-client-id", default=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""))
    parser.add_argument("--google-oauth-client-secret", default=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""))
    parser.add_argument("--github-oauth-client-id", default=os.environ.get("GITHUB_OAUTH_CLIENT_ID", ""))
    parser.add_argument("--github-oauth-client-secret", default=os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", ""))
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    args, unknown = parser.parse_known_args(sys.argv[1:])
    return args

def get_config() -> Config:
    args = parse_args()
    return Config(**vars(args))


# placeholder for dependencies, will be replaced during the app initialization
def config() -> Config:
    raise RuntimeError("Config dependency not initialized yet.")


ConfigDependency = Annotated[Config, Depends(config)]
