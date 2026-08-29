"""Backfill observations for sessions that failed before the agent ran (#932).

A session that died during setup recorded ``SessionCompleted{failed}`` in the
domain lane and NOTHING in observability, so it was countable in one place and
invisible in the other. ``SessionLifecycleManager`` now records a
``session_error`` at failure, but only for sessions that fail from here on.

It writes ``session_error`` and NEVER ``session_summary``: a summary is a
USAGE record that cost queries select on, and these sessions have no usage to
report. Recovering ``execution_id``/``phase_id`` from the matching
``SessionStarted`` event keeps the backfilled failures visible to
workflow-filtered queries, which a NULL attribution would hide.

This replays the same fact for historical sessions, reading it from the
``SessionCompleted`` event that already carries the status and error.

Idempotent: skips any session that already has an observation, so re-running
cannot double-count. Dry-run by default.

    uv run python scripts/backfill/backfill_failed_session_observations.py
    uv run python scripts/backfill/backfill_failed_session_observations.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import asyncpg

from syn_shared.events import SESSION_ERROR

_TERMINAL_STATUSES = ("failed", "cancelled")

# Sessions with a terminal SessionCompleted and no observability rows at all.
_ORPHANS_QUERY = """
WITH completed AS (
    SELECT
        convert_from(payload, 'UTF8')::jsonb AS body,
        to_timestamp(timestamp_unix_ms / 1000.0) AS completed_at
    FROM events
    WHERE event_type = 'SessionCompleted'
),
terminal AS (
    SELECT
        body->>'session_id' AS session_id,
        body->>'status' AS status,
        body->>'error_message' AS error_message,
        completed_at
    FROM completed
    WHERE body->>'status' = ANY($1)
),
-- Attribution comes from the session's own StartSession event, which already
-- carries the execution and phase. Without it a backfilled failure is
-- invisible to every workflow-filtered query.
started AS (
    SELECT
        convert_from(payload, 'UTF8')::jsonb AS body,
        to_timestamp(timestamp_unix_ms / 1000.0) AS started_at
    FROM events
    WHERE event_type = 'SessionStarted'
)
SELECT
    t.session_id,
    t.status,
    t.error_message,
    t.completed_at,
    s.body->>'execution_id' AS execution_id,
    s.body->>'phase_id' AS phase_id,
    s.body->>'agent_model' AS model,
    COALESCE(s.started_at, t.completed_at) AS started_at
FROM terminal t
LEFT JOIN started s ON s.body->>'session_id' = t.session_id
WHERE NOT EXISTS (
    SELECT 1 FROM agent_events a WHERE a.session_id = t.session_id
)
ORDER BY t.completed_at
"""

_INSERT = f"""
INSERT INTO agent_events (time, event_type, session_id, execution_id, phase_id, data)
VALUES ($1, '{SESSION_ERROR}', $2, $3, $4, $5::jsonb)
"""


async def _run(dsn: str, *, apply: bool) -> int:
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(_ORPHANS_QUERY, list(_TERMINAL_STATUSES))
        if not rows:
            print("Nothing to backfill: every terminal session already has observations.")
            return 0

        print(f"{len(rows)} session(s) with no observability trace:\n")
        for row in rows:
            error = (row["error_message"] or "").splitlines()
            print(
                f"  {row['session_id']}  {row['status']:<9} "
                f"{row['completed_at']:%Y-%m-%d}  {error[0][:70] if error else ''}"
            )

        if not apply:
            print("\nDry run. Re-run with --apply to write these observations.")
            return 0

        written = 0
        for row in rows:
            payload = {
                "status": row["status"],
                "error_message": row["error_message"],
                "model": row["model"],
                "backfilled": True,
            }
            # Placed on the session's START, matching how live usage is
            # attributed, rather than on the moment it gave up.
            await conn.execute(
                _INSERT,
                row["started_at"],
                row["session_id"],
                row["execution_id"],
                row["phase_id"],
                json.dumps(payload),
            )
            written += 1
        print(f"\nWrote {written} observation(s).")
        return 0
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument(
        "--dsn",
        default=os.environ.get("SYN_TIMESCALE_DSN") or os.environ.get("DATABASE_URL"),
        help="Postgres DSN (default: $SYN_TIMESCALE_DSN or $DATABASE_URL)",
    )
    args = parser.parse_args()
    if not args.dsn:
        parser.error("no DSN: pass --dsn or set SYN_TIMESCALE_DSN")
    return asyncio.run(_run(args.dsn, apply=args.apply))


if __name__ == "__main__":
    sys.exit(main())
