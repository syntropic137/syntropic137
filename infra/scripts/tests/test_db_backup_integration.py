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

A restore never destroys the database it replaces: a damaged archive is
refused before anything changes, a restore that does not verify leaves the
live database untouched, and a successful one keeps the old database aside.
"""

from __future__ import annotations

import asyncio
import re
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


def _sh(
    container, *cmd: str, database: str = "syn", backup_dir: str = "/tmp/pre-restore"
) -> tuple[int, str]:
    result = container.exec_run(
        list(cmd),
        environment={
            "PGHOST": "localhost",
            "PGUSER": "syn",
            "PGPASSWORD": _PASSWORD,
            "PGDATABASE": database,
            "SYN_BACKUP_DIR": backup_dir,
        },
    )
    return result.exit_code, result.output.decode()


def _script(
    container, *args: str, database: str = "syn", backup_dir: str = "/tmp/pre-restore"
) -> tuple[int, str]:
    return _sh(
        container,
        "sh",
        "/opt/db-backup/syn-db-backup.sh",
        *args,
        database=database,
        backup_dir=backup_dir,
    )


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

    assert _sh(timescaledb, "mkdir", "-p", "/tmp/backups", "/tmp/pre-restore")[0] == 0
    code, out = _script(timescaledb, "backup", "/tmp/backups")
    assert code == 0, out
    line = next(line for line in out.splitlines() if line.startswith("backup ok: "))
    return line.removeprefix("backup ok: ").split(" ")[0]


def _restore(container, backup: str, database: str, *flags: str, backup_dir: str = "") -> str:
    code, out = _script(
        container,
        "restore",
        backup,
        *flags,
        database=database,
        backup_dir=backup_dir or "/tmp/pre-restore",
    )
    assert code == 0, out
    return out


def _databases(container, like: str) -> list[str]:
    return _sql(
        container, f"select datname from pg_database where datname like '{like}' order by 1"
    ).splitlines()


def _populated(container, backup: str, db: str) -> dict[str, int]:
    """DB restored from BACKUP plus one row only it holds; its row counts."""
    _restore(container, backup, db)
    _sql(container, "insert into public.idempotency (key) values ('only-in-target')", db)
    return _counts(container, db)


_MARKER = "select count(*) from public.idempotency where key = 'only-in-target'"


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

    def test_force_backs_up_then_replaces_and_keeps_the_old_database(
        self, timescaledb, backup_file
    ):
        db = "syn_force"
        before = _populated(timescaledb, backup_file, db)
        pre = "/tmp/pre-restore-force"
        assert _sh(timescaledb, "mkdir", "-p", pre)[0] == 0

        out = _restore(timescaledb, backup_file, db, "--force", backup_dir=pre)

        assert _sql(timescaledb, _MARKER, db) == "0"
        assert _counts(timescaledb, db) == _counts(timescaledb, "syn")
        # The replaced database is renamed aside, whole, not dropped.
        aside = re.search(r"kept as database '(syn_pre_restore_\w+)'", out)
        assert aside, out
        assert aside.group(1) in _databases(timescaledb, "syn\\_pre\\_restore\\_%")
        assert _counts(timescaledb, aside.group(1)) == before
        assert _sql(timescaledb, _MARKER, aside.group(1)) == "1"
        # And backed up first, into a verified archive that holds the marker.
        code, listing = _sh(timescaledb, "ls", pre)
        assert code == 0
        dumps = [n for n in listing.split() if n.endswith(".dump")]
        assert len(dumps) == 1, listing
        assert f"{dumps[0]}.manifest" in listing.split()
        assert not _databases(timescaledb, "syn\\_restore\\_%"), "staging database left behind"


class TestNothingIsLost:
    """Every refusal leaves the live database exactly as it was."""

    @staticmethod
    def _copy(container, backup: str, name: str, *, size: int | None = None) -> str:
        """BACKUP and its manifest under /tmp/damaged/NAME, the dump cut to SIZE bytes."""
        target = f"/tmp/damaged/{name}"
        cut = f"head -c {size} {backup}" if size is not None else f"cat {backup}"
        code, out = _sh(
            container,
            "sh",
            "-c",
            f"mkdir -p /tmp/damaged && {cut} > {target} && cp {backup}.manifest {target}.manifest",
        )
        assert code == 0, out
        return target

    @staticmethod
    def _toc_survives(container, path: str) -> bool:
        return _sh(container, "pg_restore", "--list", path)[0] == 0

    def _truncated_after_toc(self, container, backup: str, name: str) -> str:
        """A copy cut right after its table of contents: it lists, its rows are gone.

        The shortest prefix `pg_restore --list` still reads, found by bisection:
        exactly the file the old `--list`-only guard accepted.
        """
        size = int(_sh(container, "stat", "-c", "%s", backup)[1])
        path = f"/tmp/damaged/{name}"
        fails, lists = 0, size
        while lists - fails > 1:
            mid = (fails + lists) // 2
            self._copy(container, backup, name, size=mid)
            if self._toc_survives(container, path):
                lists = mid
            else:
                fails = mid
        self._copy(container, backup, name, size=lists)
        assert lists < size
        assert self._toc_survives(container, path)
        return path

    def _assert_untouched(self, container, db: str, before: dict[str, int]) -> None:
        assert _counts(container, db) == before
        assert _sql(container, _MARKER, db) == "1"
        assert not _databases(container, "syn\\_restore\\_%"), "staging database left behind"

    def test_truncated_archive_is_refused_before_anything_changes(
        self, timescaledb, backup_file
    ):
        db = "syn_truncated"
        before = _populated(timescaledb, backup_file, db)
        asides = _databases(timescaledb, "syn\\_pre\\_restore\\_%")
        damaged = self._truncated_after_toc(timescaledb, backup_file, "truncated.dump")

        code, out = _script(timescaledb, "restore", damaged, "--force", database=db)

        assert code != 0
        assert "does not match its manifest" in out, out
        self._assert_untouched(timescaledb, db, before)
        assert _databases(timescaledb, "syn\\_pre\\_restore\\_%") == asides

    def test_truncated_archive_with_a_matching_checksum_fails_in_staging(
        self, timescaledb, backup_file
    ):
        """Past the checksum (a manifest rewritten to match), staging still stops it."""
        db = "syn_truncated_staged"
        before = _populated(timescaledb, backup_file, db)
        damaged = self._truncated_after_toc(timescaledb, backup_file, "rehashed.dump")
        code, out = _sh(
            timescaledb,
            "sh",
            "-c",
            f'sed -i "s/^sha256 .*/sha256 $(sha256sum < {damaged} | cut -d" " -f1)/"'
            f" {damaged}.manifest",
        )
        assert code == 0, out

        code, out = _script(timescaledb, "restore", damaged, "--force", database=db)

        assert code != 0
        assert "was not changed" in out, out
        self._assert_untouched(timescaledb, db, before)

    def test_restored_row_counts_must_match_the_manifest(self, timescaledb, backup_file):
        db = "syn_short_rows"
        before = _populated(timescaledb, backup_file, db)
        claimed = self._copy(timescaledb, backup_file, "overclaimed.dump")
        # The archive is intact; its manifest says events held one more row.
        code, out = _sh(
            timescaledb,
            "sh",
            "-c",
            "awk '$1 == \"rows\" && $3 == \"public.events\" { $2 = $2 + 1 } { print }' "
            f"{claimed}.manifest > /tmp/m && cat /tmp/m > {claimed}.manifest",
        )
        assert code == 0, out

        code, out = _script(timescaledb, "restore", claimed, "--force", database=db)

        assert code != 0
        assert "public.events: restored 250 rows, backup holds 251" in out, out
        self._assert_untouched(timescaledb, db, before)

    def test_archive_without_a_manifest_is_refused(self, timescaledb, backup_file):
        db = "syn_no_manifest"
        before = _populated(timescaledb, backup_file, db)
        bare = self._copy(timescaledb, backup_file, "bare.dump")
        assert _sh(timescaledb, "rm", f"{bare}.manifest")[0] == 0

        code, out = _script(timescaledb, "restore", bare, "--force", database=db)

        assert code != 0
        assert "no manifest" in out, out
        self._assert_untouched(timescaledb, db, before)

    def test_force_restores_nothing_when_the_backup_first_fails(self, timescaledb, backup_file):
        db = "syn_force_no_backup"
        before = _populated(timescaledb, backup_file, db)
        asides = _databases(timescaledb, "syn\\_pre\\_restore\\_%")

        code, out = _script(
            timescaledb,
            "restore",
            backup_file,
            "--force",
            database=db,
            backup_dir="/tmp/no-such-backup-dir",
        )

        assert code != 0
        assert f"could not back up '{db}' first" in out, out
        self._assert_untouched(timescaledb, db, before)
        assert _databases(timescaledb, "syn\\_pre\\_restore\\_%") == asides
