"""validate() refuses a database the dashboard reads cannot run against (E1).

/metrics and the contribution heatmap read agent_summary_usage,
agent_turn_usage_rollup and agent_event_day_rollup unconditionally. With
SYN_SKIP_AUTO_CREATE_TABLES=true ensure_schema() creates none of them, so they
exist only if migrations 005 and 007 were applied by hand. Before this check
that deployment started cleanly and answered 503 on every dashboard request.
A missing or disabled trigger is the quieter failure: the tables stay and stop
growing.

The database is a double: what is under test is which catalogue answers make
startup fail, not what Postgres says. The rollup itself is exercised against a
live server in packages/syn-domain/tests/integration/.
"""

from __future__ import annotations

import pytest

from syn_adapters.events.models import EXPECTED_COLUMNS
from syn_adapters.events.schema import (
    SUMMARY_USAGE_TABLE,
    TURN_USAGE_ROLLUP_TABLE,
    USAGE_ROLLUP_TRIGGER,
    EventStoreSchema,
    SchemaValidationError,
)

pytestmark = pytest.mark.unit

_DAY_ROLLUP_TRIGGER = "agent_events_day_rollup"


class _Conn:
    """agent_events is correct; the named rollup objects are absent."""

    def __init__(self, *, absent: frozenset[str] = frozenset()) -> None:
        self.absent = absent
        self.statements: list[str] = []

    async def execute(self, query: str, *_args: object) -> str:
        self.statements.append(query)
        return "OK"

    async def fetch(self, query: str, *_args: object) -> list[dict[str, str]]:
        return [
            {"column_name": name, "data_type": data_type.split()[0]}
            for name, data_type in EXPECTED_COLUMNS.items()
        ]

    async def fetchval(self, query: str, *_args: object) -> object:
        if "pg_trigger" in query:
            return not any(f"tgname = '{name}'" in query for name in self.absent)
        return not any(f"to_regclass('{name}')" in query for name in self.absent)


async def test_a_database_holding_every_rollup_validates() -> None:
    await EventStoreSchema(skip_auto_create=True).validate(_Conn())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("absent", "migration"),
    [
        (SUMMARY_USAGE_TABLE, "007_agent_usage_rollup.sql"),
        (TURN_USAGE_ROLLUP_TABLE, "007_agent_usage_rollup.sql"),
        (USAGE_ROLLUP_TRIGGER, "007_agent_usage_rollup.sql"),
        ("agent_event_day_rollup", "005_agent_event_day_rollup.sql"),
        (_DAY_ROLLUP_TRIGGER, "005_agent_event_day_rollup.sql"),
    ],
)
async def test_a_missing_rollup_object_fails_startup_and_names_its_migration(
    absent: str, migration: str
) -> None:
    with pytest.raises(SchemaValidationError) as raised:
        await EventStoreSchema(skip_auto_create=True).validate(
            _Conn(absent=frozenset({absent}))  # type: ignore[arg-type]
        )
    message = str(raised.value)
    assert absent in message
    assert migration in message


async def test_skip_auto_create_startup_runs_no_ddl_and_still_checks_the_rollups() -> None:
    """The deployed path: no CREATE reaches the database, and validation still bites."""
    conn = _Conn(absent=frozenset({SUMMARY_USAGE_TABLE}))
    with pytest.raises(SchemaValidationError):
        await EventStoreSchema(skip_auto_create=True).ensure_schema(conn)  # type: ignore[arg-type]
    ddl = [s for s in conn.statements if "CREATE" in s and "EXTENSION" not in s]
    assert ddl == []
