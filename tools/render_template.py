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
import os
import sys
import subprocess
from pathlib import Path
from time import sleep

from fixbackend.notification.email import email_messages
from fixbackend.notification.email.email_messages import TemplatesPath

template = sys.argv[1]
additional_context = dict(user_id="test")
last_mod_time = None


def file_has_changed(filepath: Path):
    """Check if a file has been modified."""
    current_mod_time = os.path.getmtime(filepath)
    global last_mod_time
    if current_mod_time != last_mod_time:
        last_mod_time = current_mod_time
        return True
    return False


path = TemplatesPath / template
rendered_path = Path(f"~/{template}").expanduser().absolute()
while True:
    if file_has_changed(path):
        with open(rendered_path, "w+") as f:
            f.write(email_messages.render(template, **additional_context))
        subprocess.run(["open", "-g", rendered_path])
        print(f"file {template} changed. rerenderd.")
    sleep(0.1)
