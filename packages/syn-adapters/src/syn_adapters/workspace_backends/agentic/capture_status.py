"""Turn the session-store finalizer's log lines into a structured outcome.

Session capture is deliberately FAIL-OPEN: a store outage, a bad token, or a
timeout must never stop a workflow from running. That policy is only defensible
if the platform can afterwards answer, per execution, whether capture actually
happened - otherwise "does not block execution" quietly becomes "loses sessions
and says nothing".

The finalizer inside the workspace container reports on stderr and always exits
0, by design: it must not fail a container whose agent work succeeded, and it
deliberately withholds the exporter's own output because that binary is
operator-supplied and could print an auth header. So its log lines are the only
signal that crosses the container boundary, and this module is where they stop
being prose and become something a projection can store and a dashboard can show.

Parsing text is not the ideal contract - a versioned JSON result would be - and
that belongs in the exporter CLI substandard. Until it exists, this parser is
the seam, and it is written to degrade honestly: anything it cannot classify
becomes UNKNOWN rather than a guess, because a wrong "captured" is worse than an
admitted "not sure".
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CaptureOutcome",
    "CaptureState",
    "parse_capture_status",
]

#: Every finalizer line starts with this. Anything else in the container's
#: stderr belongs to the agent or the entrypoint and is not ours to interpret.
_PREFIX = "[finalize] session-store"

_RE_COMPLETE = re.compile(r"upload complete")
_RE_TIMEOUT = re.compile(r"upload TIMED OUT after (\d+)s")
_RE_FAILED = re.compile(r"upload FAILED \(rc=(\d+)\)")
_RE_INCOMPLETE = re.compile(r"sweep INCOMPLETE \(([^)]*)\)")
_RE_UNPARSEABLE = re.compile(r"produced no parseable summary line")

#: Counters the exporter prints on its summary line. Declared here so the names
#: this side reads are spelled once.
_COUNTERS = ("discovered", "skipped_unchanged", "uploaded", "accepted", "duplicate", "failed")


class CaptureState(StrEnum):
    """What happened to this execution's sessions.

    Deliberately NOT a boolean. "Did capture work" has more than two useful
    answers, and collapsing them is how an operator ends up unable to tell a
    store outage from a misconfiguration from a run that had nothing to send.
    """

    DISABLED = "disabled"
    """No store configured. The overwhelmingly common case, and not a problem."""

    CAPTURED = "captured"
    """The sweep completed cleanly. Sessions are in the store."""

    INCOMPLETE = "incomplete"
    """The sweep ran and something did not land - failed, rejected, or oversize.

    Distinct from FAILED: the exporter worked and the STORE or a transcript was
    the problem, so retrying the same call unchanged will usually repeat it.
    """

    FAILED = "failed"
    """The exporter could not complete - non-zero exit, or a timeout.

    Usually transient (store unreachable, slow network), so this is the state
    worth retrying and the state a backfill should target.
    """

    UNKNOWN = "unknown"
    """The finalizer said something this parser does not recognise.

    Never silently treated as success. An unrecognised line means the finalizer
    changed and this parser did not, which is a defect to surface rather than a
    reason to assume the best.
    """


class CaptureOutcome(BaseModel):
    """Structured result of one workspace's session-capture finalize."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: CaptureState
    reason: str | None = Field(
        default=None,
        description="Human-readable cause when not CAPTURED. Never contains a credential: it is built from the finalizer's own lines, which deliberately withhold the exporter's output.",
    )
    counters: dict[str, int] = Field(
        default_factory=dict,
        description="Counters recovered from the exporter summary line, when it emitted one.",
    )

    @property
    def needs_backfill(self) -> bool:
        """True when sessions may exist that the store does not have.

        UNKNOWN counts: if the parser cannot tell, the safe assumption is that
        something is missing, because a backfill that re-sends an already-stored
        session is a no-op (the store dedups on content_hash) while a skipped
        backfill is a permanently lost transcript. The costs are not symmetric.
        """
        return self.state in (CaptureState.FAILED, CaptureState.INCOMPLETE, CaptureState.UNKNOWN)


def _counters_from(text: str) -> dict[str, int]:
    found: dict[str, int] = {}
    for name in _COUNTERS:
        m = re.search(rf"\b{name}=(\d+)", text)
        if m:
            found[name] = int(m.group(1))
    return found


def parse_capture_status(container_stderr: str, *, store_enabled: bool) -> CaptureOutcome:
    """Classify one workspace's capture outcome from its container stderr.

    Args:
        container_stderr: everything the container wrote to stderr.
        store_enabled: whether a session store was configured for this workspace.
            Passed in rather than inferred: with no store the finalizer emits
            NOTHING, which is indistinguishable from a finalizer that never ran.
    """
    if not store_enabled:
        return CaptureOutcome(state=CaptureState.DISABLED)

    lines = [ln for ln in container_stderr.splitlines() if _PREFIX in ln]
    if not lines:
        return CaptureOutcome(
            state=CaptureState.UNKNOWN,
            reason=(
                "a store was configured but the finalizer emitted nothing; it may not "
                "have run (container killed without a stop?) or its output was not captured"
            ),
        )

    counters = _counters_from(container_stderr)
    # Last line wins: the finalizer's terminal verdict is its final word.
    for line in reversed(lines):
        if _RE_COMPLETE.search(line):
            return CaptureOutcome(state=CaptureState.CAPTURED, counters=counters)
        if m := _RE_TIMEOUT.search(line):
            return CaptureOutcome(
                state=CaptureState.FAILED,
                reason=f"upload timed out after {m.group(1)}s",
                counters=counters,
            )
        if m := _RE_FAILED.search(line):
            return CaptureOutcome(
                state=CaptureState.FAILED,
                reason=f"exporter exited {m.group(1)}",
                counters=counters,
            )
        if m := _RE_INCOMPLETE.search(line):
            return CaptureOutcome(
                state=CaptureState.INCOMPLETE,
                reason=f"sweep incomplete: {m.group(1).strip()}",
                counters=counters,
            )
        if _RE_UNPARSEABLE.search(line):
            return CaptureOutcome(
                state=CaptureState.UNKNOWN,
                reason="the exporter produced no parseable summary line",
                counters=counters,
            )

    return CaptureOutcome(
        state=CaptureState.UNKNOWN,
        reason="the finalizer reported, but in a form this parser does not recognise",
        counters=counters,
    )
