"""A backup restores into a working TimescaleDB, hypertables included.

Runs the real ``docker/db-backup/syn-db-backup.sh`` inside the same image the
self-host ``db-backup`` service uses, against a database shaped like the real
one: the event store tables, a projection table with its checkpoint, and
``agent_events`` as a hypertable spread over several chunks.

Listing the archive is not enough. A hypertable restored without
``timescaledb_pre_restore()`` / ``timescaledb_post_restore()`` can come back as
a catalog that no longer routes inserts to chunks, so this restores, compares
every table's row count, and then writes and reads the hypertable.
"""

from __future__ import annotations

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
_TABLES = (
    "public.events",
    "public.aggregates",
    "public.idempotency",
    "event_store.events",
    "public.agent_events",
    "public.workflow_summaries",
    "public.projection_checkpoints",
)

_SEED = """
create extension if not exists timescaledb;
create schema event_store;
create table public.events (
    global_nonce bigserial primary key, aggregate_id text not null,
    aggregate_nonce bigint not null, event_type text not null, payload jsonb not null);
create table public.aggregates (aggregate_id text primary key, last_nonce bigint not null);
create table public.idempotency (key text primary key, created_at timestamptz not null default now());
create table event_store.events (id bigserial primary key, event_type text not null);
create table public.agent_events (
    time timestamptz not null, session_id text not null, event_type text not null, data jsonb);
select create_hypertable('public.agent_events', 'time', chunk_time_interval => interval '1 day');
create table public.workflow_summaries (workflow_id text primary key, runs int not null);
create table public.projection_checkpoints (projection text primary key, position bigint not null);

insert into public.events (aggregate_id, aggregate_nonce, event_type, payload)
    select 'wf-' || (g % 7), g, 'WorkflowExecutionStarted', jsonb_build_object('n', g)
    from generate_series(1, 250) g;
insert into public.aggregates select 'wf-' || g, g from generate_series(0, 6) g;
insert into public.idempotency (key) select 'k' || g from generate_series(1, 11) g;
insert into event_store.events (event_type) select 'legacy' from generate_series(1, 5);
insert into public.agent_events
    select timestamptz '2026-10-01' + g * interval '1 hour', 's' || (g % 3), 'tool_use', '{}'
    from generate_series(0, 119) g;
insert into public.workflow_summaries select 'wf-' || g, g from generate_series(0, 6) g;
insert into public.projection_checkpoints values ('workflow_summaries', 250);
"""


@pytest.fixture(scope="module")
def timescaledb() -> Iterator[object]:
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer(_IMAGE, username="syn", password=_PASSWORD, dbname="syn")
    container.with_volume_mapping(str(_SCRIPT_DIR), "/opt/db-backup", "ro")
    with container:
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
    return {t: int(_sql(container, f"select count(*) from {t}", database)) for t in _TABLES}


@pytest.fixture(scope="module")
def backup_file(timescaledb) -> str:
    code, out = _sh(timescaledb, "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", _SEED)
    assert code == 0, out
    assert int(_sql(timescaledb, "select count(*) from timescaledb_information.chunks")) > 1

    assert _sh(timescaledb, "mkdir", "-p", "/tmp/backups")[0] == 0
    code, out = _script(timescaledb, "backup", "/tmp/backups")
    assert code == 0, out
    line = next(line for line in out.splitlines() if line.startswith("backup ok: "))
    return line.removeprefix("backup ok: ").split(" ")[0]


class TestRoundTrip:
    def test_restore_into_an_empty_database_reproduces_every_table(self, timescaledb, backup_file):
        code, out = _script(timescaledb, "restore", backup_file, database="syn_restored")
        assert code == 0, out

        source = _counts(timescaledb, "syn")
        assert all(n > 0 for n in source.values()), source
        assert _counts(timescaledb, "syn_restored") == source

    def test_restored_hypertable_still_routes_and_queries_by_time(self, timescaledb, backup_file):
        db = "syn_restored"
        assert (
            _sql(
                timescaledb,
                "select count(*) from timescaledb_information.hypertables"
                " where hypertable_name = 'agent_events'",
                db,
            )
            == "1"
        )
        # A time that no restored chunk covers: the insert needs a new chunk.
        _sql(
            timescaledb,
            "insert into public.agent_events values"
            " (timestamptz '2026-12-25 12:00', 'after-restore', 'tool_use', '{}')",
            db,
        )
        assert (
            _sql(
                timescaledb,
                "select count(*) from public.agent_events"
                " where time >= timestamptz '2026-10-02' and time < timestamptz '2026-10-03'",
                db,
            )
            == "24"
        )
        assert (
            _sql(
                timescaledb,
                "select session_id from public.agent_events where time > timestamptz '2026-12-01'",
                db,
            )
            == "after-restore"
        )
        # post_restore must have run: the database is no longer in restore mode.
        assert _sql(timescaledb, "show timescaledb.restoring", db) == "off"

    def test_refuses_a_populated_database_and_changes_nothing(self, timescaledb, backup_file):
        _sql(
            timescaledb,
            "insert into public.idempotency (key) values ('only-in-target')",
            "syn_restored",
        )

        code, out = _script(timescaledb, "restore", backup_file, database="syn_restored")

        assert code == 3, out
        assert "public.events" in out
        assert (
            _sql(
                timescaledb,
                "select count(*) from public.idempotency where key = 'only-in-target'",
                "syn_restored",
            )
            == "1"
        )

    def test_force_replaces_a_populated_database(self, timescaledb, backup_file):
        code, out = _script(timescaledb, "restore", backup_file, "--force", database="syn_restored")

        assert code == 0, out
        assert _counts(timescaledb, "syn_restored") == _counts(timescaledb, "syn")
