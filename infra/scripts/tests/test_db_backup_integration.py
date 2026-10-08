"""A backup restores into a working TimescaleDB, hypertables included.

Runs the real ``docker/db-backup/syn-db-backup.sh`` inside the same image the
self-host ``db-backup`` service uses, against a database shaped like the real
one: the event store tables, a projection table with its checkpoint, and
``agent_events`` built by the production ``EventStoreSchema.ensure_schema()``
- hypertable, compression settings, rollup tables and their triggers - with
its older chunks actually compressed.

Listing the archive is not enough. A hypertable restored without
``timescaledb_pre_restore()`` / ``timescaledb_post_restore()`` can come back as
a catalog that no longer routes inserts to chunks, so this restores, compares
every table's row count, and then writes and reads the hypertable.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_DIR = _ROOT / "docker" / "db-backup"
_IMAGE = yaml.safe_load((_ROOT / "docker" / "docker-compose.yaml").read_text())["services"][
    "timescaledb"
]["image"]

_PASSWORD = "backup-test"
#: Seeded below; the comparison itself covers every user table in the database.
_SEEDED_TABLES = (
    "public.events",
    "public.aggregates",
    "public.idempotency",
    "event_store.events",
    "public.agent_events",
    "public.agent_event_day_rollup",
    "public.workflow_summaries",
    "public.projection_checkpoints",
)
#: agent_events chunks before this are compressed after seeding.
_COMPRESS_BEFORE = "2026-10-04"

_SEED = """
create extension if not exists timescaledb;
create schema event_store;
create table public.events (
    global_nonce bigserial primary key, aggregate_id text not null,
    aggregate_nonce bigint not null, event_type text not null, payload jsonb not null);
create table public.aggregates (aggregate_id text primary key, last_nonce bigint not null);
create table public.idempotency (key text primary key, created_at timestamptz not null default now());
create table event_store.events (id bigserial primary key, event_type text not null);
create table public.workflow_summaries (workflow_id text primary key, runs int not null);
create table public.projection_checkpoints (projection text primary key, position bigint not null);

insert into public.events (aggregate_id, aggregate_nonce, event_type, payload)
    select 'wf-' || (g % 7), g, 'WorkflowExecutionStarted', jsonb_build_object('n', g)
    from generate_series(1, 250) g;
insert into public.aggregates select 'wf-' || g, g from generate_series(0, 6) g;
insert into public.idempotency (key) select 'k' || g from generate_series(1, 11) g;
insert into event_store.events (event_type) select 'legacy' from generate_series(1, 5);
insert into public.workflow_summaries select 'wf-' || g, g from generate_series(0, 6) g;
insert into public.projection_checkpoints values ('workflow_summaries', 250);
"""

#: Written after the production schema exists, so its rollup triggers fire.
_AGENT_EVENTS = f"""
insert into public.agent_events (time, event_type, session_id, execution_id, phase_id, data)
    select timestamptz '2026-10-01' + g * interval '1 hour', 'tool_use', 's' || (g % 3),
           'exec-' || (g % 2), 'phase-1', '{{}}'
    from generate_series(0, 119) g;
select compress_chunk(c)
    from show_chunks('public.agent_events', older_than => timestamptz '{_COMPRESS_BEFORE}') c;
"""

_USER_TABLES = """
select format('%I.%I', table_schema, table_name) from information_schema.tables
where table_type = 'BASE TABLE'
  and table_schema not in ('pg_catalog', 'information_schema')
  and table_schema not like '\\_timescaledb%' and table_schema not like 'timescaledb\\_%'
order by 1
"""


async def _production_schema(dsn: str) -> None:
    """Exactly what the api runs at startup to create agent_events."""
    import asyncpg

    from syn_adapters.events.schema import EventStoreSchema

    conn = await asyncpg.connect(dsn)
    try:
        await EventStoreSchema().ensure_schema(conn)
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def timescaledb() -> Iterator[object]:
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer(_IMAGE, username="syn", password=_PASSWORD, dbname="syn")
    container.with_volume_mapping(str(_SCRIPT_DIR), "/opt/db-backup", "ro")
    with container:
        dsn = (
            f"postgresql://syn:{_PASSWORD}@{container.get_container_host_ip()}:"
            f"{container.get_exposed_port(5432)}/syn"
        )
        asyncio.run(_production_schema(dsn))
        yield container.get_wrapped_container()


def _sh(container, *cmd: str, database: str = "syn") -> tuple[int, str]:
    result = container.exec_run(
        list(cmd),
        environment={
            "PGHOST": "localhost",
            "PGUSER": "syn",
            "PGPASSWORD": _PASSWORD,
            "PGDATABASE": database,
        },
    )
    return result.exit_code, result.output.decode()


def _script(container, *args: str, database: str = "syn") -> tuple[int, str]:
    return _sh(container, "sh", "/opt/db-backup/syn-db-backup.sh", *args, database=database)


def _sql(container, sql: str, database: str = "syn") -> str:
    code, out = _sh(
        container, "psql", "-X", "-At", "-v", "ON_ERROR_STOP=1", "-c", sql, database=database
    )
    assert code == 0, out
    return out.strip()


def _counts(container, database: str) -> dict[str, int]:
    """Row count of every user table in DATABASE, keyed by qualified name."""
    tables = _sql(container, _USER_TABLES, database).splitlines()
    return {t: int(_sql(container, f"select count(*) from {t}", database)) for t in tables}


def _compressed_chunks(container, database: str) -> int:
    return int(
        _sql(
            container,
            "select count(*) from timescaledb_information.chunks"
            " where hypertable_name = 'agent_events' and is_compressed",
            database,
        )
    )


@pytest.fixture(scope="module")
def backup_file(timescaledb) -> str:
    for sql in (_SEED, _AGENT_EVENTS):
        code, out = _sh(timescaledb, "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql)
        assert code == 0, out
    assert int(_sql(timescaledb, "select count(*) from timescaledb_information.chunks")) > 1
    assert _compressed_chunks(timescaledb, "syn") >= 3

    assert _sh(timescaledb, "mkdir", "-p", "/tmp/backups")[0] == 0
    code, out = _script(timescaledb, "backup", "/tmp/backups")
    assert code == 0, out
    line = next(line for line in out.splitlines() if line.startswith("backup ok: "))
    return line.removeprefix("backup ok: ").split(" ")[0]


def _restore(container, backup: str, database: str, *flags: str) -> None:
    code, out = _script(container, "restore", backup, *flags, database=database)
    assert code == 0, out


class TestRoundTrip:
    """Each test restores into its own database, so they hold under xdist."""

    def test_restore_into_an_empty_database_reproduces_every_table(self, timescaledb, backup_file):
        _restore(timescaledb, backup_file, "syn_restored")

        source = _counts(timescaledb, "syn")
        assert all(source[t] > 0 for t in _SEEDED_TABLES), source
        assert _counts(timescaledb, "syn_restored") == source

    def test_restored_hypertable_still_routes_and_queries_by_time(self, timescaledb, backup_file):
        db = "syn_hypertable"
        _restore(timescaledb, backup_file, db)
        hypertables = _sql(
            timescaledb,
            "select count(*) from timescaledb_information.hypertables"
            " where hypertable_name = 'agent_events'",
            db,
        )
        assert hypertables == "1"
        # A time that no restored chunk covers: the insert needs a new chunk.
        _sql(
            timescaledb,
            "insert into public.agent_events"
            " (time, event_type, session_id, execution_id, phase_id, data) values"
            " (timestamptz '2026-12-25 12:00', 'tool_use', 'after-restore',"
            " 'exec-after', 'phase-1', '{\"after\": true}')",
            db,
        )
        one_day = _sql(
            timescaledb,
            "select count(*) from public.agent_events"
            " where time >= timestamptz '2026-10-02' and time < timestamptz '2026-10-03'",
            db,
        )
        assert one_day == "24"
        # That day lives in a compressed chunk: it came back compressed, and
        # decompresses on read.
        assert _compressed_chunks(timescaledb, db) == _compressed_chunks(timescaledb, "syn")
        newest = _sql(
            timescaledb,
            "select session_id from public.agent_events where time > timestamptz '2026-12-01'",
            db,
        )
        assert newest == "after-restore"
        # post_restore must have run: the database is no longer in restore mode.
        assert _sql(timescaledb, "show timescaledb.restoring", db) == "off"

    def test_refuses_a_populated_database_and_changes_nothing(self, timescaledb, backup_file):
        db = "syn_refuse"
        _restore(timescaledb, backup_file, db)
        _sql(timescaledb, "insert into public.idempotency (key) values ('only-in-target')", db)

        code, out = _script(timescaledb, "restore", backup_file, database=db)

        assert code == 3, out
        assert "public.events" in out
        marker = "select count(*) from public.idempotency where key = 'only-in-target'"
        assert _sql(timescaledb, marker, db) == "1"

    def test_force_replaces_a_populated_database(self, timescaledb, backup_file):
        db = "syn_force"
        _restore(timescaledb, backup_file, db)
        _sql(timescaledb, "insert into public.idempotency (key) values ('only-in-target')", db)

        _restore(timescaledb, backup_file, db, "--force")

        marker = "select count(*) from public.idempotency where key = 'only-in-target'"
        assert _sql(timescaledb, marker, db) == "0"
        assert _counts(timescaledb, db) == _counts(timescaledb, "syn")
