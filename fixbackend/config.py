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

import argparse
from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings


def strip_nulls(input: Any) -> Any:
    if not isinstance(input, dict):
        return input
    return {k: strip_nulls(v) for k, v in input.items() if v}


parser = argparse.ArgumentParser(
    prog="FIX Backend",
)

parser.add_argument("--database_url")


class Config(BaseSettings):
    database_url: str = "mysql+aiomysql://mariadb:mariadb@127.0.0.1:3306/mariadb"
    secret: str = "secret"
    google_oauth_client_id: str = "42"
    google_oauth_client_secret: str = "42"
    github_oauth_client_id: str = "42"
    github_oauth_client_secret: str = "42"


# production implementation
@lru_cache()
def get_config() -> Config:
    args, unknown = parser.parse_known_args()
    config_vals = strip_nulls(vars(args))
    config = Config(**config_vals)
    return config
