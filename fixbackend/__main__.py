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

import uvicorn
from fixbackend.config import parse_args, get_config
from alembic.config import Config
from alembic import command
from fixbackend.alembic_startup_utils import database_revision, all_migration_revisions


def main() -> None:
    args = parse_args()

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", get_config().database_url)
    if args.skip_migrations:
        known_revisions = all_migration_revisions(alembic_cfg)
        last_revision = known_revisions[0]
        db_revision = database_revision(alembic_cfg)

        # valid cases:
        # * db is at the same revision as the last migration, or
        # * we rolled back and db revision is not in the list of known migration revisions
        if db_revision in known_revisions and db_revision != last_revision:
            raise RuntimeError("Database is not up to date")
    else:
        command.upgrade(alembic_cfg, "head")

    uvicorn.run(
        "fixbackend.app:setup_process",
        host="0.0.0.0",
        log_level="info",
        ws_ping_interval=1,
        ws_ping_timeout=5,
        ssl_ca_certs=args.ca_cert,
        ssl_certfile=args.host_cert,
        ssl_keyfile=args.host_key,
        factory=True,
    )


if __name__ == "__main__":
    main()
