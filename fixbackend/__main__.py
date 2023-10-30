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


def main() -> None:
    args = parse_args()
    if not args.skip_migrations:
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", get_config().database_url)
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
    )


if __name__ == "__main__":
    main()
