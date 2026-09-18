"""Every agent_events index must reach a database, not just the .sql file (#1338).

#1338 arrived with a composite index, ``idx_events_session_type``, that had
been applied BY HAND to one running database - and the question of how a new
install would ever get it. The answer turned out to be worse than "through the
migration": nothing applies ``projection_stores/migrations/*.sql`` at all.
Every reference to ``002_agent_events.sql`` is a docstring or a drift test.
``EventStoreSchema._create_indexes`` is the only code that creates these
indexes anywhere, so an index written only into the migration reaches no
database ever, while reviewing that migration makes it look shipped.

``test_schema_consistency.py`` did not catch that, because it compares COLUMNS
between the two declarations and never indexes. That is the hop this file
closes: both directions of it, so neither declaration can quietly gain or lose
an index the other does not have.

The test asserts against the DDL the running code EXECUTES rather than against
a list of index names kept here. A list would be a third declaration of the
same thing, drifting from both of the two it is supposed to reconcile.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from syn_adapters.events.schema import EventStoreSchema

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run none of them (#1065).
pytestmark = pytest.mark.unit

_MIGRATION = (
    Path(__file__).parent.parent.parent
    / "src/syn_adapters/projection_stores/migrations/002_agent_events.sql"
)

# CREATE INDEX [IF NOT EXISTS] <name> ON agent_events [USING <method>] (<cols>)
_CREATE_INDEX = re.compile(
    r"CREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+ON\s+agent_events\s*"
    r"(?:USING\s+\w+\s*)?\(([^)]*)\)",
    re.IGNORECASE | re.DOTALL,
)


def _indexes(sql: str) -> dict[str, str]:
    """Map index name -> normalised column list, for every agent_events index."""
    return {
        match.group(1).lower(): " ".join(match.group(2).split()).lower()
        for match in _CREATE_INDEX.finditer(sql)
    }


def _migration_indexes() -> dict[str, str]:
    return _indexes(_MIGRATION.read_text())


def _executed_indexes() -> dict[str, str]:
    """The indexes `_create_indexes` actually issues, read from its source.

    Reading the source is deliberate. The alternative - calling the method with
    a recording connection double - proves the same thing but ties the test to
    asyncpg's connection protocol, and this file's whole subject is a string of
    DDL rather than any behaviour around it.
    """
    return _indexes(inspect.getsource(EventStoreSchema._create_indexes))  # noqa: SLF001


def test_the_two_declarations_of_the_index_set_agree() -> None:
    """The migration and the Python DDL must declare the same indexes.

    Failing here means one of them was edited alone. Which one tells you what
    broke: missing from Python, the index reaches no database; missing from the
    migration, the canonical schema no longer describes what runs.
    """
    migration = _migration_indexes()
    executed = _executed_indexes()

    # GIN indexes are excluded from neither side; if the migration grows one
    # that Python lacks, that is exactly the drift this test is for.
    assert executed == migration, (
        "agent_events index declarations have drifted.\n"
        f"  only in 002_agent_events.sql: {sorted(set(migration) - set(executed))}\n"
        f"  only in _create_indexes:      {sorted(set(executed) - set(migration))}\n"
        f"  differing columns: "
        f"{sorted(n for n in set(migration) & set(executed) if migration[n] != executed[n])}\n"
        "Both files must change together: only the Python side is ever executed "
        "(nothing applies the migration), only the SQL side is reviewed as canonical."
    )


@pytest.mark.parametrize(
    ("id_column", "index_name"),
    [("session_id", "idx_events_session_type"), ("execution_id", "idx_events_execution_type")],
)
def test_the_id_and_event_type_pair_each_cost_query_filters_on_is_indexed(
    id_column: str, index_name: str
) -> None:
    """Both id+event_type pairs the cost read paths filter on must be indexed.

    Every cost query in session_cost/ and execution_cost/ pairs an id with an
    event_type (`session_id = ANY($1) AND event_type = $2`, or the execution_id
    form). An index leading on the id and then on `time` does not serve that
    pair - it narrows by id and rechecks event_type per row - which is why
    #1338's hand-applied index was needed in the first place.

    Asserted against the EXECUTED DDL, because that is the copy that decides
    whether a fresh install has the index.
    """
    executed = _executed_indexes()

    assert index_name in executed, (
        f"{index_name} is not created by EventStoreSchema._create_indexes, so no "
        f"fresh install has it and every {id_column}+event_type cost query rechecks "
        f"event_type per row. Present in the migration: {sorted(_migration_indexes())}"
    )
    columns = executed[index_name]
    assert columns.startswith(id_column), (
        f"{index_name} must LEAD on {id_column} to narrow the scan before "
        f"event_type is considered; it is ({columns})"
    )
    assert "event_type" in columns, (
        f"{index_name} must include event_type - that is the column the cost "
        f"queries filter on and the existing idx_events_* indexes lack; it is ({columns})"
    )
