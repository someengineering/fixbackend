from nox_poetry import session, Session
from tempfile import TemporaryDirectory

locations = ["fixbackend", "tests", "noxfile.py"]


@session(python=["3.11"])
def black(session: Session) -> None:
    opts = ["--line-length", "120", "--check"]
    args = session.posargs or locations + opts
    session.install("black")
    session.run("black", *args)


@session(python=["3.11"])
def flake8(session: Session) -> None:
    opts = ["--max-line-length", "120"]
    args = session.posargs or locations + opts
    session.install("flake8")
    session.run("flake8", *args)


@session(python=["3.11"])
def test(session: Session) -> None:
    args = session.posargs or ["--cov"]
    # workaround for CI to create a wheel outside the project folder
    with TemporaryDirectory() as tmpdir:
        session.run("cp", "-R", ".", str(tmpdir), external=True)
        with session.chdir(tmpdir):
            session.poetry.installroot()
    session.install("pytest", "pytest-cov", "pytest-asyncio", "sqlalchemy-utils", ".")
    session.run("pytest", *args)


@session(python=["3.11"])
def mypy(session: Session) -> None:
    opts = ["--install-type", "--non-interactive", "--python-version", "3.11"]
    args = session.posargs or locations + opts
    session.install("mypy", ".")
    session.run("mypy", *args)
