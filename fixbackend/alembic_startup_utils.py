from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.environment import EnvironmentContext
from typing import Any, List


# copied from alembic current command
def database_revision(config: Config) -> str:  # pragma: no cover
    script = ScriptDirectory.from_config(config)

    current: List[str] = []

    def collect_version(rev: Any, context: Any) -> Any:
        for rev in script.get_all_current(rev):
            current.append(rev.revision)

        return []

    with EnvironmentContext(config, script, fn=collect_version, dont_mutate=True):
        script.run_env()

    if len(current) != 1:
        raise ValueError("Multiple heads detected")

    return current[0]


def all_migration_revisions(config: Config) -> List[str]:  # pragma: no cover
    script = ScriptDirectory.from_config(config)
    return [rev.revision for rev in script.iterate_revisions("head", "base")]
