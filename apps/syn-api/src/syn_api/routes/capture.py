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

THE BIAS IS TOWARDS REPORTING WORK. A backfill that re-sends an already-stored
session is a no-op, because the store dedups on content hash. A backfill that
is skipped is a permanently lost transcript. Those costs are not symmetric, so
anything unreadable here reads as UNKNOWN and counts as needing backfill.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query

from syn_adapters.workspace_backends.agentic.capture_observation import (
    SESSION_CAPTURE_OBSERVATION,
)
from syn_adapters.workspace_backends.agentic.capture_result import (
    SUPPORTED_SCHEMA_VERSION,
)
from syn_adapters.workspace_backends.agentic.capture_status import CaptureState
from syn_api._wiring import get_event_store
from syn_api.types import CaptureStatusEntry, CaptureStatusResponse

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

router = APIRouter(prefix="/capture", tags=["capture"])

#: Bounded so a caller cannot ask for the whole event store by accident.
MAX_LIMIT = 500

#: Only these close the case. Everything else - including a state this build
#: does not recognise - is work.
_SETTLED = frozenset({CaptureState.CAPTURED, CaptureState.DISABLED})


def _text(value: object) -> str | None:
    """A string, or None for anything else.

    The stored payload is a JSON blob written by another process, so a field
    can hold whatever that process put there. Narrowing here keeps a non-string
    from reaching a typed response field, where it would raise inside the
    serializer or arrive at a client as something it cannot parse.
    """
    return value if isinstance(value, str) else None


#: Any URL-shaped run, however it is quoted or punctuated around.
_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s'\"<>]+")

_REDACTED = "<redacted url>"


def _scrubbed(reason: str | None) -> str | None:
    """Reason text with URLs removed.

    The exporter builds these messages by interpolating the store URL - see
    capture_result's mismatch verdict, which quotes both the reported and the
    configured one. That URL is operator-supplied and can carry the write token
    in its userinfo, query or even its host, which is exactly why the startup
    posture line logs no part of it either.

    The rest of the sentence is what an operator needs ("exporter reported
    success against a different store"), and it survives. The destination is
    already identified by the deployment fields, which cannot contain a secret.
    """
    if reason is None:
        return None
    return _URL.sub(_REDACTED, reason)


def _parsed_time(value: object) -> datetime | None:
    """The query adapter hands back an ISO string, not a datetime."""
    from datetime import datetime as _dt

    text = _text(value)
    if text is None:
        return None
    try:
        return _dt.fromisoformat(text)
    except ValueError:
        return None


def _state_of(payload: Mapping[str, object]) -> CaptureState:
    """The recorded verdict, or UNKNOWN if it cannot be trusted.

    Three ways to end up UNKNOWN, all deliberate:

    * the payload schema is a version this build does not understand, so its
      fields may not mean what they are named;
    * the state is missing;
    * the state is a value this build does not recognise, which is the same
      situation as a version skew but without the version to warn us.

    Guessing in any of these cases risks recording "safely stored" about a
    transcript nobody has.
    """
    if payload.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        return CaptureState.UNKNOWN

    raw = _text(payload.get("state"))
    if raw is None:
        return CaptureState.UNKNOWN

    try:
        return CaptureState(raw)
    except ValueError:
        return CaptureState.UNKNOWN


def _to_entry(event: Mapping[str, object]) -> CaptureStatusEntry | None:
    """Project one stored observation row into the response shape.

    The row is an ENVELOPE: identity and time at the top level, the capture
    payload nested under ``data``. An earlier version read every field from the
    top level, which is the shape the WRITER flattens before insert - not the
    shape the reader returns. Every healthy row projected as UNKNOWN needing
    backfill, and the tests did not catch it because they asserted against the
    invented shape rather than the query adapter's contract.

    Returns None only when there is no session id: such a row cannot be acted
    on, and the caller counts it rather than discarding it silently.
    """
    session_id = _text(event.get("session_id"))
    if not session_id:
        return None

    raw_payload = event.get("data")
    payload: Mapping[str, object] = raw_payload if isinstance(raw_payload, dict) else {}
    state = _state_of(payload)

    return CaptureStatusEntry(
        session_id=session_id,
        execution_id=_text(event.get("execution_id")),
        phase_id=_text(event.get("phase_id")),
        workspace_id=_text(payload.get("workspace_id")),
        recorded_at=_parsed_time(event.get("time")),
        state=state.value,
        # DERIVED from the state, never read from the stored flag. A flag that
        # disagreed with its own state - through version skew or a partial
        # write - would otherwise be trusted to close a case it cannot close.
        needs_backfill=state not in _SETTLED,
        reason=_scrubbed(_text(payload.get("reason"))),
        partition=_text(payload.get("partition")),
        expected_deployment=_text(payload.get("expected_deployment")),
        origin_deployment=_text(payload.get("origin_deployment")),
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
        events: Sequence[Mapping[str, object]] = await store.query_recent_by_types(
            [SESSION_CAPTURE_OBSERVATION], limit=limit
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"capture status unavailable: {exc}") from exc

    entries = [entry for entry in map(_to_entry, events) if entry is not None]
    # Counted over the scanned window, not over what is returned: an operator
    # filtering to the backlog still wants to know how big it is.
    backlog = sum(1 for entry in entries if entry.needs_backfill)
    # NOT dropped quietly. A verdict with no session id is still evidence that
    # something happened, and a response that omitted it entirely could read as
    # "all clear" while a failure sat unattributable in the store.
    unattributable = len(events) - len(entries)

    if needs_backfill:
        entries = [entry for entry in entries if entry.needs_backfill]

    return CaptureStatusResponse(
        total=len(entries),
        needs_backfill_count=backlog,
        unattributable_count=unattributable,
        scanned=len(events),
        # The database applies the limit BEFORE this filter, so a full window
        # means older failures may exist beyond it. Without this a caller could
        # read an empty backlog off a page that simply did not reach them,
        # which is a wrong answer rather than a missing feature.
        truncated=len(events) >= limit,
        entries=entries,
    )
