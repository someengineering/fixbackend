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

from nox_poetry import session, Session

locations = ["fixbackend", "tests", "noxfile.py"]


@session(python=["3.11"])
def black(session: Session) -> None:
    opts = ["--line-length", "120", "--check"]
    args = session.posargs or locations + opts
    session.install("black")
    session.run("black", *args)


@session(python=["3.11"])
def flake8(session: Session) -> None:
    opts = ["--max-line-length", "999"]  # checked via black
    args = session.posargs or locations + opts
    session.install("flake8")
    session.run("flake8", *args)


@session(python=["3.11"])
def test(session: Session) -> None:
    args = session.posargs or ["--cov"]
    session.run_always("poetry", "install", external=True)
    session.run("pytest", *args)


@session(python=["3.11"])
def mypy(session: Session) -> None:
    opts = ["--python-version", "3.11"]
    args = session.posargs or locations + opts
    session.install("mypy", ".")
    session.run("mypy", *args)
