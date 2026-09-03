# Upgrading TimescaleDB 2.25.1 -> 2.29.2 (PostgreSQL 16.11 -> 16.15)

Security upgrade for **CVE-2026-14669**, a heap buffer overflow in PostgreSQL's
`to_char()` reached through oversized POSIX timezone abbreviations. An
authenticated database session can use it to execute code as the OS account
running Postgres. Public PoC exists. Fixed in PostgreSQL **18.6, 17.11, 16.15,
15.19 and 14.24**.

Everything below was executed against the selfhost deployment on 2026-09-03.
Measurements are operator-reported from that run unless a command to reproduce
them is given.

## Why this is not a major-version migration

`timescale/timescaledb:2.29.2-pg16` ships PostgreSQL **16.15**. The PostgreSQL
major version does not change, so the data directory is compatible and there is
**no dump/restore**. The only moving part is the TimescaleDB extension,
2.25.1 -> 2.29.2.

Pin an explicit `<ts-version>-pg<major>` tag, and verify the version the
*server* reports, not what the tag name implies.

> **`docker run` reads the local cache and never consults the registry.** Always
> `docker pull` first, or compare digests, which does not touch the cache:
>
>     docker buildx imagetools inspect timescale/timescaledb:2.29.2-pg16 \
>       --format '{{.Manifest.Digest}}'
>
> Observed 2026-09-03: `latest-pg16` and `2.29.2-pg16` both returned
> `sha256:289d55704b1b3ee8263cd3805c6930f9cd54506835a8f19f9b85dad17d5c5a8a`.
> `latest-pg16` is mutable, so that will not stay true. Reading a version out of
> an unpulled image is how this document originally came to claim, wrongly, that
> `latest-pg16` was stuck on 16.11.

## Compatibility

There are **four** backward-incompatible entries between 2.25.1 and 2.29.2, not
one (2.27.0 contributes two). Each was checked against the production catalog
rather than assumed inapplicable:

| release | backward-incompatible change | applies here? |
|---|---|---|
| 2.27.0 | Bloom filter sparse indexes over **`int2`** source columns can make `SELECT` miss matching rows. Upstream blocks the upgrade on affected databases. | **No.** The only bloom indexes are on `execution_id` and `event_type`, both `text`. |
| 2.27.0 | Composite bloom filter metadata renamed. Queries keep working, but 2.27+ cannot use composite filters built by 2.26 until a catalog-only [migration script](https://github.com/timescale/timescaledb-extras/blob/main/utils/2.27.x-fix-composite-bloom-columns.sql) renames them. | Not a correctness or availability risk. Optional. |
| 2.28.0 | **Adaptive chunking removed.** | **No.** `chunk_target_size = 0` on every hypertable. |
| 2.29.0 | PostgreSQL 15 support removed. | **No.** We run 16. |

Also checked and clear: `time_bucket_ng` was removed in 2.25.0, already behind
us, and is not used. `_timescaledb_catalog.chunk_constraint` was dropped in
2.28.0 and replaced by a compatibility view; nothing in this repo reads it.
TimescaleDB 2.29 supports PostgreSQL 16, 17 and 18, so major 16 remains a
supported target rather than a dead end.

### Preflight

Run this before every upgrade, because the answers depend on the data, not on
this document. **Both counts must be 0.**

    docker exec -i syn137-timescaledb psql -X -At -v ON_ERROR_STOP=1 -U syn -d syn <<'SQL'
    -- 2.28.0: adaptive chunking removed. Enablement is chunk_target_size > 0.
    -- Do NOT test chunk_sizing_func_name: an adaptive hypertable keeps the
    -- default 'calculate_chunk_interval', so a name test silently passes an
    -- affected database. Confirmed on this deployment, where the name is
    -- 'calculate_chunk_interval' and target_size is 0: the name carries no signal.
    select 'adaptive_chunking=' || count(*)
      from _timescaledb_catalog.hypertable
     where chunk_target_size > 0;

    -- 2.27.0: bloom filter sparse indexes over int2 source columns. The hazard
    -- lives in the columnstore index configuration (a JSONB array of
    -- {type, column, source}), not in the source column type, so counting
    -- smallint columns both over- and under-reports.
    select 'int2_bloom_indexes=' || count(*)
      from _timescaledb_catalog.compression_settings cs
      cross join lateral jsonb_array_elements(coalesce(cs.index, '[]'::jsonb)) ix
      join pg_attribute a on a.attrelid = cs.relid and a.attname = ix->>'column'
     where ix->>'type' = 'bloom'
       and a.atttypid = 'int2'::regtype;

    -- Show the work: every bloom index, its column type, and whether it was
    -- created automatically or configured explicitly.
    select 'bloom: ' || (ix->>'column') || ' type=' || format_type(a.atttypid, null)
        || ' source=' || (ix->>'source')
      from _timescaledb_catalog.compression_settings cs
      cross join lateral jsonb_array_elements(coalesce(cs.index, '[]'::jsonb)) ix
      join pg_attribute a on a.attrelid = cs.relid and a.attname = ix->>'column'
     where ix->>'type' = 'bloom'
     group by 1;
    SQL

Non-zero `adaptive_chunking` must be disabled before upgrading. Non-zero
`int2_bloom_indexes` needs judgement: since 2.28.2 upstream drops
*automatically* created incompatible filters during the update (`source=default`
above), while *explicitly configured* ones still block it. Resolve those by hand
rather than trusting the auto-drop.

The real upgrade is self-guarding regardless: upstream blocks `ALTER EXTENSION`
outright on an affected database, so a successful `ALTER` is stronger evidence
than any preflight. The preflight exists so you learn about a blocker before
taking an outage, not after.

### Watch item, not a blocker

There is an open upstream regression in 2.28 through 2.29.2 affecting
`GROUP BY time_bucket(...)` plans
([timescale/timescaledb#10489](https://github.com/timescale/timescaledb/issues/10489)).
This repo has that shape in the contribution heatmap
(`packages/syn-domain/.../contribution_heatmap/TimescaleHeatmapQuery.py`, served
at `/api/v1/insights/contribution-heatmap`). Capture timings for it **before**
you recreate the container. On 2026-09-03 that step was skipped, so there is no
before-number for this deployment; after the upgrade it served in 1.46-1.94s
over four runs, which is now the only available baseline.

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

Run the whole procedure under `set -euo pipefail`. Without `pipefail` the guards
below report the exit status of `jq` or `tail` rather than of `curl` or
`pg_restore`, so a failed check looks like a passed one.

    set -euo pipefail
    export CF=/root/.syntropic137/docker-compose.syntropic137.yaml
    sudo docker compose -f "$CF" config --services   # must list timescaledb + the 4 consumers

The application calls `CREATE EXTENSION IF NOT EXISTS timescaledb`, which is a
**no-op** when the extension already exists at the older version. The extension
update is therefore a manual step and will not happen on its own.

In rehearsal the server did **not** refuse queries between starting the 2.29.2
image and running the `ALTER`: it served reads and writes normally with the
extension still registered at 2.25.1. Treat that as one observation, not a
guarantee. Either way, do not rely on a hard failure to tell you the step was
missed. Check `extversion` explicitly.

### Before the outage

1. **Repin and pull.** Both must happen *before* writers stop, or the download
   lands inside the downtime, and `compose pull` against a file still pinned to
   2.25.1 merely re-pulls 2.25.1:

       sudo cp -n "$CF" "$CF.bak-cve-14669"
       sudo sed -i 's|timescale/timescaledb:2.25.1-pg16|timescale/timescaledb:2.29.2-pg16|g' "$CF"
       sudo docker compose -f "$CF" config --images | grep timescaledb   # must show 2.29.2-pg16
       sudo docker compose -f "$CF" pull timescaledb

2. **Run the preflight** above. Both counts 0.

### The outage

3. **Confirm nothing is executing**, using the server-side filter rather than
   filtering one page client-side, and failing closed if the API cannot be read.
   An empty response is not evidence of an idle queue:

       curl -sS --fail -m 25 -o /tmp/running.json \
         "http://100.114.86.77:8137/api/v1/executions?status=running&page_size=100"
       python3 -c "import json;d=json.load(open('/tmp/running.json'));print('running:',len(d['executions']))"

4. **Stop the writers.** Recreating only `timescaledb` does *not* stop its
   consumers: they hold restart policies and reconnect the moment Postgres is
   healthy, so they would write during both the backup and the `ALTER`.

       sudo docker compose -f "$CF" stop api collector event-store gateway
       docker exec syn137-timescaledb psql -X -At -U syn -d syn -c \
         "select count(*) from pg_stat_activity where datname='syn' and pid <> pg_backend_pid();"

5. **Back up, and validate the archive.** Shell redirection creates the file
   before `pg_dump` writes to it, so its existence proves nothing. Validate with
   the image's own client rather than assuming host PostgreSQL tools exist:

       docker exec syn137-timescaledb pg_dump -U syn -d syn -Fc > pre-2.29.2.dump
       docker run --rm -i -v "$PWD":/b timescale/timescaledb:2.25.1-pg16 \
         pg_restore --list /b/pre-2.29.2.dump | tail -5     # must list objects
       sha256sum pre-2.29.2.dump | tee pre-2.29.2.dump.sha256

   Record the counts you will compare afterwards (step 8).

   `pg_dump` warns about circular foreign keys on `hypertable`, `chunk` and
   `continuous_agg`. Expected, and about *restore*, not the dump.

6. **Recreate only the database service.** `--force-recreate` is required:
   without it Compose can keep the existing container when only the tag changed.

       sudo docker compose -f "$CF" up -d --force-recreate timescaledb

7. **Update the extension**, in a fresh session, on its own:

       docker exec syn137-timescaledb psql -X -v ON_ERROR_STOP=1 -U syn -d syn \
         -c 'ALTER EXTENSION timescaledb UPDATE;'

8. **Verify from what the server reports**, not from the tag. Both
   `public.events` and `event_store.events` exist on this deployment; the domain
   event stream is `public.events`:

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
   to step 5. Do not start consumers until that holds.

9. **Start the consumers.**

       sudo docker compose -f "$CF" start api collector event-store gateway

10. **Verify on a real read path, not `/health`.** During a past outage
    `/health` answered in 36 ms while `/api/v1/executions` took 23 s. Check an
    execution list, an execution detail, and an artifact download.

## Rollback

Decide by where it failed.

**Before step 7 (`ALTER`).** Nothing is committed. Repin back and recreate:

    sudo sed -i 's|2.29.2-pg16|2.25.1-pg16|' "$CF"
    sudo docker compose -f "$CF" up -d --force-recreate timescaledb
    sudo docker compose -f "$CF" start api collector event-store gateway

This returns the box to PostgreSQL 16.11 and therefore **reopens
CVE-2026-14669**. It buys availability, it is not a resting state. Fix forward
the same day.

**After step 7.** The extension has been updated in place. Timescale documents
single-step minor downgrades only, so a four-minor in-place downgrade is outside
the tested path: recover by restoring the step 5 dump.

Preserve the failed state. **Never `docker compose down -v`.** Copy the existing
volume aside rather than deleting it, and restore into a fresh empty one:

    # 1. Stop everything that could write, including consumers if already started.
    sudo docker compose -f "$CF" stop api collector event-store gateway timescaledb

    # 2. Preserve the failed volume, and verify the copy is non-empty.
    FAILED=syn137_db_data_failed_$(date +%Y%m%d)
    docker volume create "$FAILED"
    docker run --rm -v syn137_db_data:/from:ro -v "$FAILED":/to \
      alpine sh -c 'cp -a /from/. /to/ && ls /to | head'

    # 3. Only after the copy is confirmed, recreate an empty restore target.
    docker volume rm syn137_db_data && docker volume create syn137_db_data

    # 4. Repin to the dump's extension version and start the database ALONE.
    sudo sed -i 's|2.29.2-pg16|2.25.1-pg16|' "$CF"
    sudo docker compose -f "$CF" up -d --force-recreate timescaledb
    until docker exec syn137-timescaledb pg_isready -U syn -d syn; do sleep 1; done

    # 5. Restore. These are two different tools: psql for the SQL, and
    #    pg_restore streamed in over stdin. No parallel -j: upstream warns it
    #    does not restore TimescaleDB catalogs correctly.
    docker exec syn137-timescaledb psql -X -v ON_ERROR_STOP=1 -U syn -d syn \
      -c 'CREATE EXTENSION IF NOT EXISTS timescaledb;'
    docker exec syn137-timescaledb psql -X -At -U syn -d syn \
      -c 'SELECT timescaledb_pre_restore();'
    docker exec -i syn137-timescaledb pg_restore -U syn -d syn --no-owner --no-acl \
      < pre-2.29.2.dump
    docker exec syn137-timescaledb psql -X -At -U syn -d syn \
      -c 'SELECT timescaledb_post_restore();'

    # 6. Re-run the step 8 verification, THEN start consumers.
    sudo docker compose -f "$CF" start api collector event-store gateway

Then re-attempt the upgrade rather than leaving the platform on 16.11.

## Rehearsals

**Forward path**, against a throwaway restore of real `agent_events` data
(1151 rows, 1 hypertable, 1 compressed chunk):

| | before | after |
|---|---|---|
| PostgreSQL | 16.11 | **16.15** |
| timescaledb extension | 2.25.1 | **2.29.2** |
| hypertables / compressed chunks | 1 / 1 | 1 / 1 |
| `agent_events` rows | 1151 | 1151 |
| policy jobs | 3 | 3 |

Afterwards, reads against compressed chunks returned, an insert succeeded, and
`decompress_chunk()` ran cleanly. No discrepancy was observed in the counts and
rows checked; that is a sample, not a proof of zero data loss.

**Rollback path**, using the real production dump (17 MB, 283 objects, validated
with `pg_restore --list`) restored into a fresh volume on a clean 2.25.1-pg16
container via the sequence above:

| | production | restored |
|---|---|---|
| PostgreSQL / extension | 16.11 / 2.25.1 | 16.11 / 2.25.1 |
| hypertables | 1 | 1 |
| compressed chunks | 9 | 9 |
| `public.events` | 7980 | 7980 |
| `public.agent_events` | 86855 | **86837** |
| policy jobs | 3 | 3 |
| continuous aggregates | 0 | 0 |

Zero restore errors reported by `pg_restore`.

The 18-row gap in `agent_events` is **consistent with** writes landing after the
dump's snapshot: the dump was taken while consumers were still running, and the
production count was read about a minute later. That was not proven by keyed
comparison, and the same symptom could in principle come from an incomplete
restore, so treat it as consistent-with rather than caused-by. Either way it is
the reason step 4 stops the writers before step 5 backs up: a backup taken with
writers live is a rollback target that loses whatever was written after the
snapshot.
