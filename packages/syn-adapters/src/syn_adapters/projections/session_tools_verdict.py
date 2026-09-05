"""The two things every ToolOperation writer has to get right, in one place.

Three converters build a `ToolOperation` - the standard one in
`session_tools_dispatch`, and the subagent and git ones in
`session_tools_converters`. Each of them independently decided how to name a
row and what to say about whether it went wrong, and all three got it wrong in
the same way (#1196):

    {"operation_type": "session_error",
     "operation_id": "-2026-09-05T02:51:43.414696+00:00",
     "tool_name": "", "success": true}

The one observation whose entire purpose is to record that something went
wrong said nothing about what went wrong, claimed it succeeded, and named
itself with a leading hyphen because an absent tool id was concatenated with a
timestamp anyway.

Fixing that at the `session_error` call site would have left the identical
defect in the other two - that is the four-writers-one-contract finding from
PR #1072. So the contract lives here and the writers obey it, rather than each
re-deciding it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from syn_shared.events import (
    ERROR,
    SESSION_ERROR,
    SUBAGENT_STARTED,
    TOOL_EXECUTION_FAILED,
    TOOL_EXECUTION_STARTED,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Observation types whose NAME is the failure. A row of one of these types
#: reports `success=False` whatever its payload says, because the payload of a
#: session error never carried a `success` key to say it with - which is how
#: `None` reached the HTTP layer and was defaulted to `True`.
#:
#: `tool_blocked` is deliberately absent: a blocked tool is a policy decision
#: that went as designed, not an operation that failed.
FAILURE_EVENT_TYPES: frozenset[str] = frozenset(
    {SESSION_ERROR, ERROR, TOOL_EXECUTION_FAILED},
)

#: Observation types that record a beginning. There is no verdict yet, and
#: `None` says exactly that - it is not "it went fine".
_NO_VERDICT_YET: frozenset[str] = frozenset({TOOL_EXECUTION_STARTED, SUBAGENT_STARTED})

#: Where a failure reason is spelled, newest convention first. `message` is
#: NOT among them and must never be: it is in `RESERVED_OBSERVATION_KEYS`
#: (see `syn_adapters.events.store_helpers`), so a payload cannot carry one.
_REASON_KEYS: tuple[str, ...] = ("error_message", "error", "reason", "interrupt_reason")

#: What a failure says when nothing upstream said anything. Blank is the one
#: answer that is never true: something DID go wrong, and "we do not know
#: what" is a finding, not an absence.
NO_REASON_RECORDED: str = "no failure reason was recorded"


@dataclass(frozen=True)
class Verdict:
    """What an observation says about whether its subject went wrong.

    `success` is three-valued on purpose. `None` means this observation type
    carries no verdict at all - a tool that has only started, a session that
    has only begun - and it is the caller's job to render that as unknown
    rather than to collapse it into either boolean.

    `error_message` is present exactly when there is something to say, and is
    never the empty string: a failure with nothing recorded gets
    `NO_REASON_RECORDED` instead, so a reader is told the reason is missing
    rather than shown a blank field and left to guess.
    """

    success: bool | None
    error_message: str | None


def read_verdict(
    event_type: str,
    data: Mapping[str, Any],
    *,
    unrecorded: bool | None = None,
) -> Verdict:
    """The verdict for one stored observation row.

    `unrecorded` is what to report when the row itself recorded no outcome.
    Only git rows pass it: a `git_commit` observation exists because the commit
    happened, so its type alone settles the question. Every other converter
    leaves it `None`, meaning "if the row did not say, nobody knows".
    """
    success = _read_success(event_type, data.get("success"), unrecorded)
    stated = _stated_reason(*(data.get(key) for key in _REASON_KEYS))
    if success is False:
        return Verdict(success=False, error_message=stated or NO_REASON_RECORDED)
    return Verdict(success=success, error_message=stated)


def _read_success(event_type: str, recorded: object, unrecorded: bool | None) -> bool | None:
    """Whether this row's subject went wrong, from its type and its payload.

    The type wins over the payload, because for the types that ARE failures the
    payload has nothing to say: a `session_error` never carried a `success` key
    at all, and that missing key is what became `None` and then `True`.
    """
    if event_type in _NO_VERDICT_YET:
        return None
    if event_type in FAILURE_EVENT_TYPES:
        return False
    if isinstance(recorded, bool):
        return recorded
    # A completion with no usable `success` key is still a completion, so it
    # falls through to `unrecorded` like any other row rather than to True.
    return unrecorded


def _stated_reason(*candidates: object) -> str | None:
    """The first candidate that actually says something, in preference order.

    Blank and whitespace-only strings are not reasons - treating them as ones
    is how an empty message survived all the way to a user.
    """
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value
    return None


def observation_id(*parts: str | None) -> str:
    """Join the parts that are present into a row's identity.

    Absent parts are dropped here, at construction, rather than spelled as an
    empty string and left visible in the key: `f"{tool_use_id}-{when}"` for a
    session-level row - which has no tool id and never will - produced
    `-2026-09-05T02:51:43+00:00`, a malformed id advertising a field that does
    not apply to it.

    This id is a read-time identity, not stored state. It is a React key on the
    timeline and the dedup key `_accumulate_tool_stats` falls back to when a
    row has no `tool_use_id`, so it has to be deterministic (it is - every part
    comes from the row) and it has to distinguish rows that are genuinely
    different. Both callers that could lose their only distinguishing part now
    pass the event type, so two different session-level rows sharing a
    timestamp no longer collapse into one.
    """
    return "-".join(part for part in parts if part)
