from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.environment import EnvironmentContext
from typing import Any, List


def database_revision(config: Config) -> str:  # pragma: no cover
    script = ScriptDirectory.from_config(config)

    current: List[str] = []

    def display_version(rev: Any, context: Any) -> Any:
        for rev in script.get_all_current(rev):
            current.append(rev.revision)

        return []

    with EnvironmentContext(config, script, fn=display_version, dont_mutate=True):
        script.run_env()

    if len(current) != 1:
        raise ValueError("Multiple heads detected")

    return current[0]


def last_migration_revision(config: Config) -> str:  # pragma: no cover
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if len(heads) != 1:
        raise ValueError("Multiple heads detected")
    return heads[0]
