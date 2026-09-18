"""Recount the tool-call tally from agent_events (#1322).

``/sessions`` and ``/executions`` read their tool-call column from
``agent_tool_call_counts``, a tally maintained incrementally in the same
transaction as the events it counts.

A blank tally repairs itself, in every configuration: ``AgentEventStore``
refills it at startup whether or not ``SYN_SKIP_AUTO_CREATE_TABLES`` is set,
and ``rebuild_projection tool_call_counts`` recounts it on demand. A tally
that has rows in it and the WRONG rows does neither, and cannot - telling a
wrong count from a right one costs exactly the recount, so nothing cheap can
be asked first. That is what this is for, and it is the same recount either
way.

Run it when the numbers are not believable: after an import that wrote
``agent_events`` by some path that did not maintain the tally, after a restore
from a backup taken between the two, or when a count has visibly drifted.

    uv run python scripts/backfill/rebuild_tool_call_counts.py
    uv run python scripts/backfill/rebuild_tool_call_counts.py --apply

Safe against a running API. The recount empties and refills in one
transaction, so no page ever renders the gap, and it takes a lock that stops a
concurrent write committing in the middle rather than racing it - see
``syn_domain.tool_call_counts.rebuild``. Safe to run twice: the result is a
function of ``agent_events`` alone.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import asyncpg

from syn_domain import tool_call_counts

_TOTAL_SQL = f"SELECT COALESCE(SUM(tool_calls), 0)::bigint FROM {tool_call_counts.TABLE}"


async def _total(conn: asyncpg.Connection) -> int:
    return int(str(await conn.fetchval(_TOTAL_SQL)))


async def _run(dsn: str, *, apply: bool) -> int:
    conn = await asyncpg.connect(dsn)
    try:
        before = await _total(conn)
        if not apply:
            # The dry run still has to answer "would this change anything?",
            # and the only honest way to know is to do it and roll back.
            transaction = conn.transaction()
            await transaction.start()
            try:
                await tool_call_counts.rebuild(conn)  # type: ignore[arg-type]  # asyncpg satisfies the protocol
                after = await _total(conn)
            finally:
                await transaction.rollback()
            print(f"Tally holds {before} tool call(s); a recount would make it {after}.")
            print(
                "Nothing written."
                if before == after
                else f"Off by {after - before:+d}. Re-run with --apply to correct it."
            )
            return 0

        await tool_call_counts.rebuild(conn)  # type: ignore[arg-type]  # asyncpg satisfies the protocol
        after = await _total(conn)
        print(f"Recounted from agent_events: {before} -> {after} tool call(s).")
        return 0
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument(
        "--dsn",
        default=os.environ.get("SYN_TIMESCALE_DSN") or os.environ.get("DATABASE_URL"),
        help="Postgres DSN for the observability store "
        "(default: $SYN_TIMESCALE_DSN or $DATABASE_URL)",
    )
    args = parser.parse_args()
    if not args.dsn:
        parser.error("no DSN: pass --dsn or set SYN_TIMESCALE_DSN")
    return asyncio.run(_run(args.dsn, apply=args.apply))


if __name__ == "__main__":
    sys.exit(main())
