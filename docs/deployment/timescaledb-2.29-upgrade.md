# Upgrading TimescaleDB 2.25.1 -> 2.29.2 (PostgreSQL 16.11 -> 16.15)

Security upgrade for **CVE-2026-14669**, a heap buffer overflow in PostgreSQL's
`to_char()` reached through oversized POSIX timezone abbreviations. An
authenticated database session can use it to execute code as the OS account
running Postgres. Public PoC exists. Fixed in PostgreSQL 16.15 / 17.11 / 18.6.

## Why this is not a major-version migration

`timescale/timescaledb:2.29.2-pg16` ships PostgreSQL **16.15**. Staying on
major 16 means the data directory is unchanged and there is **no dump/restore**.
The only moving part is the TimescaleDB extension.

Do not reach for `latest-pg16`. That tag is stale: it still resolves to
PostgreSQL 16.11 with extension 2.24.0, so it is both unpatched and two
extension releases behind. Always pin an explicit `<ts-version>-pg<major>` tag
and verify the version the binary prints.

## Compatibility

Verified against the TimescaleDB changelog for 2.26 through 2.29:

- The only breaking change in the range is **removal of PostgreSQL 15 support**
  in 2.29.0. We run 16, so it does not apply.
- `time_bucket_ng` was removed in 2.25.0, already behind us.
- The `chunk_constraint` catalog table is deprecated as of 2.28.0. Nothing in
  this repo reads it.
- TimescaleDB 2.29 supports PostgreSQL 16, 17 and 18, so major 16 remains a
  supported target rather than a dead end.

Schema surface in this repo is one hypertable (`public.agent_events`, a Lane 2
observability projection), compression segmented by `session_id`, one
compression policy, and no continuous aggregates.

## The upgrade

The application calls `CREATE EXTENSION IF NOT EXISTS timescaledb`, which is a
**no-op** when the extension already exists at the older version. The extension
update is therefore a manual step and will not happen on its own.

Between starting the new image and running the `ALTER`, the server refuses
queries with an extension version mismatch against the loaded shared library.
That state is expected and recoverable, not damage, but it does mean the stack
is down for the duration. Drain in-flight work first.

1. Confirm nothing is executing. A container recreate drops every pool held by
   `api`, `collector` and `event-store`, which fails phases mid-flight:

       curl -s "$SYN_API/api/v1/executions?page_size=20" | jq -r \
         '.executions[] | select(.status=="running") | .workflow_execution_id'

2. Back up. The data directory is preserved across this upgrade, but take the
   dump anyway:

       docker exec <db-container> pg_dump -U syn -d syn -Fc > pre-2.29.2.dump

3. Pull the new image and recreate only the database service:

       docker compose pull timescaledb
       docker compose up -d --force-recreate timescaledb

4. Update the extension. It must run in a **fresh session, on its own**, before
   anything else touches the database:

       docker exec <db-container> psql -X -U syn -d syn \
         -c 'ALTER EXTENSION timescaledb UPDATE;'

5. Verify both versions, from what the server reports rather than the tag:

       docker exec <db-container> psql -X -At -U syn -d syn -c \
         "select version(); select extversion from pg_extension where extname='timescaledb';"

   Expect PostgreSQL **16.15** and extension **2.29.2**.

6. Restart the consumers, then check that the hypertable and its policies
   survived:

       select count(*) from timescaledb_information.hypertables;
       select count(*) from timescaledb_information.chunks where is_compressed;
       select proc_name from timescaledb_information.jobs;

   Expect 1 hypertable, the compressed chunk count you recorded in step 2, and
   the `policy_compression` / `policy_telemetry` /
   `policy_job_stat_history_retention` jobs.

7. Verify the API on a real read path, not `/health`. Per the VPS migration
   notes, `/health` answered in 36 ms while `/api/v1/executions` took 23 s
   during an outage. Check an execution list, an execution detail, and an
   artifact download.

## Rollback

Repin to `timescale/timescaledb:2.25.1-pg16` and recreate. The extension cannot
be downgraded in place, so a rollback after step 4 requires restoring the
step 2 dump into a fresh volume, using the `timescaledb_pre_restore()` /
`timescaledb_post_restore()` sequence documented in
`docs/plans/20260902_vps-migration.md`.
