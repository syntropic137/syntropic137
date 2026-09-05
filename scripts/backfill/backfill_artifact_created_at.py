"""Backfill created_at for artifacts whose ArtifactCreated event predates v4 (#1215).

274 of 1037 artifacts carry ``created_at: null``: they were written before
``ArtifactCreated`` v4 (#920) gave the event a timestamp of its own. Nothing was
lost - the append record in the ``events`` table has carried
``timestamp_unix_ms`` all along - but that column is unreachable from the read
path. ``_proto_to_envelope`` builds the metadata without it, so a replayed event
reports DECODE time; backfilling from a replay would stamp every historical
artifact with the moment of the rebuild (#924).

So this reads the column DIRECTLY, in SQL, from each artifact's own
``ArtifactCreated`` row. That is the artifact's own record, not the execution or
phase it belonged to: exact rather than a proxy, and it needs no join that could
attribute one artifact's time to another.

It writes a domain event, ``ArtifactCreationTimeRecovered``, rather than
UPDATE-ing the projection. The projection is derived state - a future
``ArtifactListProjection.VERSION`` bump rebuilds it from the event stream and
would erase any value that is not backed by an event, silently and much later.
The event survives that rebuild.

Idempotent, and not because of a WHERE clause: ``ArtifactAggregate`` refuses to
emit the event for an artifact that already has a creation time, so a second
run, an interrupted run resumed, or a concurrent run cannot double-write or
displace a real value. Re-running is always safe.

WHAT IS NOT RECOVERABLE. ``events.timestamp_unix_ms`` defaults to 0, so a row
that was appended before the writer set it reads as 1970-01-01. Those are NOT
recovered: 1970 is not this artifact's creation time, it is the absence of one
wearing a date, and a fabricated date is worse than a null because null is
honest. They are reported as unrecoverable and left null, where the list
surfaces now count them out loud (#1215).

    uv run python scripts/backfill/backfill_artifact_created_at.py
    uv run python scripts/backfill/backfill_artifact_created_at.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

import asyncpg

# An artifact is a candidate when its own ArtifactCreated row has no created_at
# in the payload. Read from the payload, not from the projection: the projection
# is what we are repairing, and asking it whether it needs repairing makes the
# script depend on the very state it is about to change.
_CANDIDATES_QUERY = """
SELECT
    body->>'artifact_id' AS artifact_id,
    body->>'workflow_id' AS workflow_id,
    timestamp_unix_ms,
    recorded_time_unix_ms
FROM (
    SELECT
        convert_from(payload, 'UTF8')::jsonb AS body,
        timestamp_unix_ms,
        recorded_time_unix_ms
    FROM events
    WHERE event_type = 'ArtifactCreated'
) rows
WHERE COALESCE(body->>'created_at', '') = ''
  AND COALESCE(body->>'artifact_id', '') <> ''
ORDER BY timestamp_unix_ms
"""

#: Where a recovered value came from. Stored on the event, so an auditor can
#: tell a value read off the append record from one somebody inferred.
_FROM_APPEND = "events.timestamp_unix_ms"
_FROM_RECORDED = "events.recorded_time_unix_ms"


@dataclass(frozen=True)
class _Candidate:
    """One undated artifact and the best source found for its creation time.

    ``when is None`` means no source was found. That is a real outcome and is
    reported as one, not smoothed over with a plausible date.
    """

    artifact_id: str
    when: datetime | None
    source: str


def _recover(artifact_id: str, append_ms: int | None, recorded_ms: int | None) -> _Candidate:
    """Pick the recoverable timestamp for one artifact, or none at all.

    ``timestamp_unix_ms`` is the event's own time and is preferred. It carries a
    ``DEFAULT 0``, so a zero means "never set" rather than 1970; in that case
    ``recorded_time_unix_ms`` - when the store accepted the append - is the
    nearest true statement available, and is recorded AS SUCH in
    ``recovered_from`` rather than passed off as the first. Zero in both is
    unrecoverable and stays null.
    """
    if append_ms:
        return _Candidate(artifact_id, datetime.fromtimestamp(append_ms / 1000, UTC), _FROM_APPEND)
    if recorded_ms:
        return _Candidate(
            artifact_id, datetime.fromtimestamp(recorded_ms / 1000, UTC), _FROM_RECORDED
        )
    return _Candidate(artifact_id, None, "")


async def _read_candidates(dsn: str) -> list[_Candidate]:
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(_CANDIDATES_QUERY)
    finally:
        await conn.close()

    return [
        _recover(str(row["artifact_id"]), row["timestamp_unix_ms"], row["recorded_time_unix_ms"])
        for row in rows
    ]


async def _apply(candidates: list[_Candidate]) -> tuple[int, int]:
    """Issue the recovery command for each candidate. Returns (written, skipped)."""
    from syn_adapters.storage.event_store_client import connect_event_store
    from syn_adapters.storage.repositories import get_artifact_repository
    from syn_domain.contexts.artifacts import (
        ManageArtifactHandler,
        RecoverArtifactCreationTimeCommand,
    )

    await connect_event_store()
    handler = ManageArtifactHandler(get_artifact_repository())

    written = skipped = 0
    for candidate in candidates:
        if candidate.when is None:
            continue
        try:
            did_write = await handler.recover_creation_time(
                RecoverArtifactCreationTimeCommand(
                    aggregate_id=candidate.artifact_id,
                    created_at=candidate.when,
                    recovered_from=candidate.source,
                )
            )
        except KeyError:
            # The event exists but the aggregate does not load - report it
            # rather than aborting the remaining rows.
            print(f"  ! {candidate.artifact_id}: no aggregate")
            continue
        written += did_write
        skipped += not did_write
    return written, skipped


async def _run(dsn: str, *, apply: bool) -> int:
    candidates = await _read_candidates(dsn)
    if not candidates:
        print("Nothing to backfill: every ArtifactCreated event states its own time.")
        return 0

    recoverable = [c for c in candidates if c.when is not None]
    unrecoverable = [c for c in candidates if c.when is None]

    print(f"{len(candidates)} artifact(s) with no created_at in their ArtifactCreated event.")
    print(f"  {len(recoverable)} recoverable from the event's own append record")
    print(f"  {len(unrecoverable)} NOT recoverable - no usable timestamp; these stay null")
    by_source: dict[str, int] = {}
    for c in recoverable:
        by_source[c.source] = by_source.get(c.source, 0) + 1
    for source, count in sorted(by_source.items()):
        print(f"    {count} from {source}")

    if not apply:
        print("\nDry run. Re-run with --apply to record these times.")
        return 0

    written, skipped = await _apply(recoverable)
    print(f"\nRecorded {written} creation time(s); {skipped} already had one.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument(
        "--dsn",
        default=os.environ.get("SYN_TIMESCALE_DSN") or os.environ.get("DATABASE_URL"),
        help="Postgres DSN for the event store (default: $SYN_TIMESCALE_DSN or $DATABASE_URL)",
    )
    args = parser.parse_args()
    if not args.dsn:
        parser.error("no DSN: pass --dsn or set SYN_TIMESCALE_DSN")
    return asyncio.run(_run(args.dsn, apply=args.apply))


if __name__ == "__main__":
    sys.exit(main())
