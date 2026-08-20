"""Session-capture status: what was captured, and what still needs a backfill.

Capture writes its verdict to the observability lane (Lane 2), where until now
nothing could read it back. An operator could see a WARNING at startup and a
log line per phase, but could not ask the one question that matters after the
fact: WHICH sessions did not reach the store.

That question is also what a backfill pass needs answered. This endpoint is
the work-list: every entry carries the spool partition the transcripts were
written to, plus the deployment they were meant to be tagged with, because the
observed values are missing in exactly the failures worth retrying.

Read-only. Nothing here re-sends anything - deciding to retry is a separate
concern from being able to see what needs retrying, and the retry itself needs
a durable archive that does not exist yet (the spool is container-local).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query

from syn_api._wiring import get_event_store
from syn_api.types import CaptureStatusEntry, CaptureStatusResponse

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

router = APIRouter(prefix="/capture", tags=["capture"])

CAPTURE_OBSERVATION_TYPE = "session_capture"

#: Bounded so a caller cannot ask for the whole event store by accident.
MAX_LIMIT = 500


def _as_datetime(value: object) -> datetime | None:
    from datetime import datetime as _dt

    return value if isinstance(value, _dt) else None


def _text(value: object) -> str | None:
    """A string, or None for anything else.

    The stored event is a loosely-typed row, so a field can hold whatever the
    writer put there. Narrowing at this boundary keeps a non-string from
    landing in a typed response field, where it would either raise inside
    FastAPI's serializer or reach a client as something it cannot parse.
    """
    return value if isinstance(value, str) else None


def _to_entry(event: Mapping[str, object]) -> CaptureStatusEntry | None:
    """Project one stored observation into the response shape.

    Returns None for an event without a session id: it cannot be acted on,
    and emitting it with an empty id would put a row in a backfill work-list
    that names nothing to retry.
    """
    session_id = _text(event.get("session_id"))
    if not session_id:
        return None

    state = _text(event.get("state"))
    return CaptureStatusEntry(
        session_id=session_id,
        execution_id=_text(event.get("execution_id")),
        phase_id=_text(event.get("phase_id")),
        workspace_id=_text(event.get("workspace_id")),
        recorded_at=_as_datetime(event.get("timestamp")),
        # An observation with no state is not readable as a verdict. UNKNOWN
        # rather than a guess, and it counts as needing backfill, because "we
        # cannot tell" must never be recorded as "it is safely stored".
        state=state or "UNKNOWN",
        needs_backfill=bool(event.get("needs_backfill", state is None)),
        reason=_text(event.get("reason")),
        partition=_text(event.get("partition")),
        expected_deployment=_text(event.get("expected_deployment")),
        origin_deployment=_text(event.get("origin_deployment")),
    )


@router.get("/status", response_model=CaptureStatusResponse)
async def get_capture_status(
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    needs_backfill: bool = Query(
        default=False,
        description="Return only sessions whose transcripts did not reach the store.",
    ),
) -> CaptureStatusResponse:
    """Recorded session-capture verdicts, newest first."""
    store = get_event_store()
    try:
        events = await store.query_recent_by_types([CAPTURE_OBSERVATION_TYPE], limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"capture status unavailable: {exc}") from exc

    entries = [entry for entry in map(_to_entry, events) if entry is not None]
    # Counted over everything read, not over what is returned: an operator
    # filtering to the backlog still wants to know how big it is.
    backlog = sum(1 for entry in entries if entry.needs_backfill)

    if needs_backfill:
        entries = [entry for entry in entries if entry.needs_backfill]

    return CaptureStatusResponse(
        total=len(entries),
        needs_backfill_count=backlog,
        entries=entries,
    )
