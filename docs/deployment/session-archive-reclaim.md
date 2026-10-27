# Session archive reclaim: dedupe and compress (#2107)

A one-time pass that shrinks the host session archive on an existing
deployment. It stores older revisions of a session as verified splice
references to the newest one, then gzip-compresses what is left.

The VPS measurement on 2026-10-26 found 36,153 objects using 53 GB. Keeping
only the newest revision per session would use 3.85 GB. Every older copy was a
strict prefix of the newest one.

Both tools run inside the API container. They take the same locks the live
workers take, verify every byte before committing, and are dry runs unless
`--apply` is given. A re-run continues from where the previous one stopped.

## 0. Preconditions

- [ ] The deployed build includes #2119 (`c24d660f`) and #2122 (the
      `session_store` block in `/health`). Check:
      `syn137-api GET /health | jq '.build.version, .session_store'`.
      `session_store` must not be null.
- [ ] Nothing else is changing the deployment: no pit stop in flight, and one
      operator at a time. Live executions may keep running.

## 1. Measure before

- [ ] Record: `syn137-api GET /health | jq '{session_store, disk: .disk.free_bytes}'`.
      Keep `stored_bytes`, `object_count`, `reference_count` and
      `filesystem_free_bytes` for the after comparison. The block is cached for
      5 minutes; `measured_at` says when it was taken.

## 2. Dedupe: dry run, then apply

Dedupe runs first. It removes most of the bytes, so the compress pass that
follows only has the remaining objects to re-encode.

- [ ] `just session-archive-dedupe --budget-minutes 120`
- [ ] Read the report. **Stop and report if `integrity failures` is above 0**;
      the listed keys are objects that do not read back as their hash. If it
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
      it finishes.

## 4. Measure after

- [ ] Wait out the 5-minute cache, then read the same fields as step 1.
- [ ] Post the before and after numbers on #2107: `stored_bytes`,
      `object_count`, `reference_count` and `filesystem_free_bytes`.
- [ ] Re-run both dry runs. Expect 0 integrity failures and nothing left to
      splice or compress.

## If something goes wrong

- **A stopped or killed run:** safe. Every step commits atomically. Re-run the
  same command and it continues.
- **Integrity failures in a dry run:** do not apply. Report the keys on #2107;
  those objects are already damaged, and the tools refuse to touch them.
- **Load:** both tools read every object they plan, inside the API container.
  `--budget-minutes` is the stop: use a smaller one if the API slows down, and
  re-run later to continue.
