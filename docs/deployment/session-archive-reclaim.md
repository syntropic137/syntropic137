# Session archive reclaim: dedupe and compress (#2107)

A one-time pass that shrinks the host session archive on an existing
deployment. It stores older revisions of a session as verified splice
references to its largest revision (by uncompressed size, normally the
newest), then gzip-compresses what is left.

The VPS measurement on 2026-10-26 found 36,153 objects using 53 GB. Keeping
only the newest revision per session would use 3.85 GB. Every older copy was a
strict prefix of the newest one.

Both tools run inside the API container. They take the same locks the live
workers take, verify every byte before committing, and are dry runs unless
`--apply` is given. A re-run is safe: committed work is skipped, not redone.
It is not a cursor, though: each run walks the archive from the start, and
compress still reads and verifies every object it already compressed.

## 0. Preconditions

- [ ] The deployed build includes #2119 (`c24d660f`) and #2122 (the
      `session_store` block in `/health`). Check:
      `syn137-api GET /health | jq '.build.version, .session_store'`.
      `session_store` must not be null. It is measured in the background, so
      the first call after a restart omits it: ask again a few seconds later.
- [ ] Nothing else is changing the deployment: no pit stop in flight, and one
      operator at a time. Live executions may keep running.

## 1. Measure before

- [ ] Record: `syn137-api GET /health | jq '{session_store, disk: .disk.free_bytes}'`.
      Keep `stored_bytes`, `object_count`, `reference_count` and
      `filesystem_free_bytes` for the after comparison. The block is cached for
      5 minutes and refreshed in the background; `measured_at` says when it
      was taken.

## 2. Dedupe: dry run, then apply

Dedupe runs first. It removes most of the bytes, so the compress pass that
follows only has the remaining objects to re-encode.

- [ ] `just session-archive-dedupe --budget-minutes 120`
- [ ] Read the report. **Stop and report if `integrity failures` is above 0**.
      Each listed key is a revision whose splice failed verification; the
      damage may be in that revision, its base, or one of the base's
      referrers, so investigate all three before applying. If it
      ends with `stopped at the time budget`, the counts are partial: re-run
      with a larger budget before deciding.
- [ ] Expect `bytes saved` to be most of `bytes before`. `not a prefix`
      revisions stay full objects, which is correct.
- [ ] `just session-archive-dedupe --apply --budget-minutes 120`. Re-run until
      the report no longer says `stopped at the time budget`. Spliced revisions
      are no longer full objects, so a finished re-run reports 0 spliced.

## 3. Compress: dry run, then apply

- [ ] `just session-archive-compress`. Stop on any integrity failure, as above.
- [ ] `just session-archive-compress --apply --budget-minutes 120`. Re-run until
      it finishes. Each re-run re-reads the objects already compressed before
      it reaches new ones, so if a run makes no progress, raise the budget
      rather than repeating it.

## 4. Measure after

- [ ] Read the same fields as step 1 once `measured_at` is after the last
      run finished: wait out the 5-minute cache, call `/health` once to start
      a refresh, then again.
- [ ] Post the before and after numbers on #2107: `stored_bytes`,
      `object_count`, `reference_count` and `filesystem_free_bytes`.
- [ ] Re-run both dry runs. Expect 0 integrity failures and nothing left to
      splice or compress.

## If something goes wrong

- **A stopped or killed run:** safe. Every step commits atomically. Re-run the
  same command; committed work is skipped.
- **Integrity failures in a dry run:** do not apply. Report the keys on #2107
  with each one's base and referrers; the failing read can be any of them,
  not necessarily the listed revision.
- **Load:** both tools read every object they plan, inside the API container.
  `--budget-minutes` is cooperative, not a hard stop: it is checked between
  objects, and dedupe groups every revision before its first check, so a run
  can overrun by that grouping plus one object's lock wait and verification.
  Use a smaller budget if the API slows down, and re-run later.
