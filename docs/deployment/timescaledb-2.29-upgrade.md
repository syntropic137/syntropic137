# Upgrading TimescaleDB 2.25.1 -> 2.29.2 (PostgreSQL 16.11 -> 16.15)

Security upgrade for **CVE-2026-14669**, a heap buffer overflow in PostgreSQL's
`to_char()` reached through oversized POSIX timezone abbreviations. An
authenticated database session can use it to execute code as the OS account
running Postgres. Public PoC exists. Fixed in PostgreSQL **18.6, 17.11, 16.15,
15.19 and 14.24**.

## Why this is not a major-version migration

`timescale/timescaledb:2.29.2-pg16` ships PostgreSQL **16.15**. The PostgreSQL
major version does not change, so the data directory is compatible and there is
**no dump/restore**. The only moving part is the TimescaleDB extension,
2.25.1 -> 2.29.2.

Pin an explicit `<ts-version>-pg<major>` tag rather than a floating one, and
verify the version the *server* reports, not what the tag name implies.

> A note on mutable tags, because getting this wrong cost a day of analysis:
> `docker run` reads the **local cache** and does not consult the registry.
> Always `docker pull` first, or compare digests with
> `docker buildx imagetools inspect <tag> --format '{{.Manifest.Digest}}'`.
> As observed 2026-09-03, `latest-pg16` and `2.29.2-pg16` resolve to the *same*
> digest (`sha256:289d5570...`). That is true today and may not be tomorrow,
> which is the reason to pin, not a reason to trust `latest`.

## Compatibility

There are **three** backward-incompatible changes between 2.25.1 and 2.29.2, not
one. Each was checked against the production catalog rather than assumed
inapplicable:

| release | backward-incompatible change | applies here? |
|---|---|---|
| 2.27.0 | Bloom filter sparse indexes on compressed **`int2`** columns can make `SELECT` miss matching rows. **Upstream blocks the upgrade** for affected databases until the bad indexes are dropped by hand. | **No.** Zero `smallint` columns on any hypertable. |
| 2.27.0 | Composite bloom filter metadata renamed. Queries keep working, but 2.27+ cannot use composite bloom filters built by 2.26 until a catalog-only [migration script](https://github.com/timescale/timescaledb-extras/blob/main/utils/2.27.x-fix-composite-bloom-columns.sql) renames them. | Not a correctness or availability risk. Optional. |
| 2.28.0 | **Adaptive chunking removed.** | **No.** Every hypertable uses the default `calculate_chunk_interval`. |
| 2.29.0 | PostgreSQL 15 support removed. | **No.** We run 16. |

Also checked and clear: `time_bucket_ng` was removed in 2.25.0, already behind
us, and is not used. `_timescaledb_catalog.chunk_constraint` was dropped in
2.28.0 and replaced by a compatibility view; nothing in this repo reads it.
TimescaleDB 2.29 supports PostgreSQL 16, 17 and 18, so major 16 remains a
supported target rather than a dead end.

Run the preflight before every upgrade, because the answers depend on the data,
not on this document:

    docker exec -i syn137-timescaledb psql -X -At -v ON_ERROR_STOP=1 -U syn -d syn <<'SQL'
    select 'int2_cols=' || count(*)
      from timescaledb_information.hypertables h
      join information_schema.columns c
        on c.table_schema = h.hypertable_schema and c.table_name = h.hypertable_name
     where c.data_type = 'smallint';
    select 'non_default_chunk_sizing=' || count(*)
      from _timescaledb_catalog.hypertable
     where chunk_sizing_func_name is distinct from 'calculate_chunk_interval';
    SQL

**Both must be 0.** A non-zero `int2_cols` means upstream will block the upgrade
and the bloom indexes must be dropped first. Do not proceed on a hunch.

### Watch item, not a blocker

There is an open upstream regression in 2.28 through 2.29.2 affecting
`GROUP BY time_bucket(...)` query plans
([timescale/timescaledb#10489](https://github.com/timescale/timescaledb/issues/10489)).
This repo has that shape in the contribution heatmap
(`packages/syn-domain/.../contribution_heatmap/TimescaleHeatmapQuery.py`).
Capture `EXPLAIN (ANALYZE, BUFFERS)` for the heatmap before and after so a
regression is measured rather than guessed at.

## The upgrade

Deployment facts this procedure assumes, all of which differ from Compose
defaults:

| | |
|---|---|
| compose file | `/root/.syntropic137/docker-compose.syntropic137.yaml` (**not** a default name, `-f` is required) |
| project | `syntropic137_selfhost` |
| database container | `syn137-timescaledb` |
| consumers holding pools | `api`, `collector`, `event-store`, `gateway` |
| API (gateway binds the tailnet IP, **not** loopback) | `http://100.114.86.77:8137` |

Set once, and confirm before any downtime starts:

    export CF=/root/.syntropic137/docker-compose.syntropic137.yaml
    sudo docker compose -f "$CF" config --services   # must list timescaledb + the 4 consumers

The application calls `CREATE EXTENSION IF NOT EXISTS timescaledb`, which is a
**no-op** when the extension already exists at the older version. The extension
update is therefore a manual step and will not happen on its own.

In rehearsal the server did **not** refuse queries between starting the 2.29.2
image and running the `ALTER`: it served reads and writes normally with the
extension still registered at 2.25.1. Treat that as one observation, not a
guarantee, and in either case do not rely on a hard failure to tell you the step
was missed. Check `extversion` explicitly.

1. **Confirm nothing is executing**, and fail closed if the API cannot be read.
   An empty response is not evidence of an idle queue:

       curl -sS --fail "http://100.114.86.77:8137/api/v1/executions?page_size=40" \
         | jq -r '.executions[] | select(.status=="running") | .workflow_execution_id'

2. **Stop the writers.** Recreating only `timescaledb` does *not* stop its
   consumers: they hold restart policies and reconnect the moment Postgres is
   healthy, so they would write during the backup and during the `ALTER`.

       sudo docker compose -f "$CF" stop api collector event-store gateway

   Then confirm the database is actually quiet, rather than assuming:

       docker exec syn137-timescaledb psql -X -At -U syn -d syn -c \
         "select count(*) from pg_stat_activity where datname='syn' and pid <> pg_backend_pid();"

3. **Back up, and validate the archive.** Shell redirection creates the file
   before `pg_dump` writes to it, so its existence proves nothing:

       docker exec syn137-timescaledb pg_dump -U syn -d syn -Fc > pre-2.29.2.dump
       pg_restore --list pre-2.29.2.dump | tail -5    # must list objects, not error
       sha256sum pre-2.29.2.dump | tee pre-2.29.2.dump.sha256

   Record the counts you will compare against afterwards: `public.events`,
   `public.agent_events`, compressed chunks, and policy jobs.

   `pg_dump` warns about circular foreign keys on `hypertable`, `chunk` and
   `continuous_agg`. That is expected, and concerns *restore*, not the dump.

4. **Pull first, then recreate only the database service.** Pull before the
   window so the download is not part of the downtime:

       sudo docker compose -f "$CF" pull timescaledb
       sudo docker compose -f "$CF" up -d --force-recreate timescaledb

   `--force-recreate` is required: without it Compose can keep the existing
   container when only the tag changed.

5. **Update the extension**, in a fresh session, on its own, before anything
   else touches the database:

       docker exec syn137-timescaledb psql -X -v ON_ERROR_STOP=1 -U syn -d syn \
         -c 'ALTER EXTENSION timescaledb UPDATE;'

6. **Verify from what the server reports**, not from the tag:

       docker exec -i syn137-timescaledb psql -X -At -v ON_ERROR_STOP=1 -U syn -d syn <<'SQL'
       select 'server_version_num=' || current_setting('server_version_num');
       select 'ext='               || extversion from pg_extension where extname='timescaledb';
       select 'hypertables='       || count(*) from timescaledb_information.hypertables;
       select 'compressed='        || count(*) from timescaledb_information.chunks where is_compressed;
       select 'events='            || count(*) from public.events;
       select 'agent_events='      || count(*) from public.agent_events;
       select 'jobs='              || coalesce(string_agg(proc_name, ','), 'none') from timescaledb_information.jobs;
       SQL

   Expect `server_version_num=160015`, `ext=2.29.2`, and every count identical
   to step 3.

7. **Start the consumers.**

       sudo docker compose -f "$CF" start api collector event-store gateway

8. **Verify on a real read path, not `/health`.** During a past outage `/health`
   answered in 36 ms while `/api/v1/executions` took 23 s. Check an execution
   list, an execution detail, and an artifact download.

## Rollback

Decide by where it failed.

**Before step 5 (`ALTER`).** Nothing is committed. Repin and recreate:

    sudo sed -i 's|2.29.2-pg16|2.25.1-pg16|' "$CF"
    sudo docker compose -f "$CF" up -d --force-recreate timescaledb
    sudo docker compose -f "$CF" start api collector event-store gateway

This returns the box to PostgreSQL 16.11 and therefore **reopens
CVE-2026-14669**. It is an availability measure, not a resting state. Fix
forward the same day.

**After step 5.** The extension has been updated in place. Downgrading four
minor versions in one step is not a supported path (Timescale supports only
single-step minor downgrades), so recovery is a restore of the step 3 dump.

Preserve the failed state instead of destroying it. Never `docker compose down -v`:

    sudo docker compose -f "$CF" stop timescaledb
    docker volume create syn137_db_data_failed_$(date +%Y%m%d)
    # copy the old volume aside, then create a fresh empty one for the restore

Restore into the fresh volume on a container matching the dump's extension
version (2.25.1), using TimescaleDB's documented sequence. Do **not** use
parallel `pg_restore -j`, which upstream warns against for hypertables:

    CREATE EXTENSION IF NOT EXISTS timescaledb;
    SELECT timescaledb_pre_restore();
    pg_restore -U syn -d syn --no-owner --no-acl < pre-2.29.2.dump
    SELECT timescaledb_post_restore();

Then re-attempt the upgrade rather than leaving the platform on 16.11.

## Rehearsed

Forward path, against a throwaway restore of real `agent_events` data
(1151 rows, 1 hypertable, 1 compressed chunk) on 2026-09-03:

| | before | after |
|---|---|---|
| PostgreSQL | 16.11 | **16.15** |
| timescaledb extension | 2.25.1 | **2.29.2** |
| hypertables / compressed chunks | 1 / 1 | 1 / 1 |
| `agent_events` rows | 1151 | 1151 |
| policy jobs | 3 | 3 |

Afterwards, reads against compressed chunks returned, an insert succeeded, and
`decompress_chunk()` ran cleanly. No data loss, no policy loss, no manual chunk
repair.

The rollback path was then rehearsed separately, on 2026-09-03, using the real
production dump (17 MB, 283 objects, validated with `pg_restore --list`)
restored into a **fresh volume** on a clean 2.25.1-pg16 container via the
documented `timescaledb_pre_restore()` / `pg_restore` / `timescaledb_post_restore()`
sequence, without parallel `-j`:

| | production | restored |
|---|---|---|
| PostgreSQL / extension | 16.11 / 2.25.1 | 16.11 / 2.25.1 |
| hypertables | 1 | 1 |
| compressed chunks | 9 | 9 |
| `public.events` | 7980 | 7980 |
| `public.agent_events` | 86855 | **86837** |
| policy jobs | 3 | 3 |
| continuous aggregates | 0 | 0 |

Zero restore errors. Note the 18-row gap in `agent_events`, and do not dismiss
it: the dump was taken while the consumers were still writing, so it was
already stale relative to a read taken a minute later. That is exactly why
step 2 stops the writers before step 3 backs up. A backup taken with writers
live is a rollback target that silently loses whatever was written after the
snapshot.
