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
    google_oauth_client_id: str
    google_oauth_client_secret: str
    github_oauth_client_id: str
    github_oauth_client_secret: str


# production implementation
@lru_cache()
def get_config() -> Config:
    args, unknown = parser.parse_known_args()
    config_vals = strip_nulls(vars(args))
    config = Config(**config_vals)
    return config
