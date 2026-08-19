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

THE STREAM IS UNTRUSTED, and that bounds what this can promise
-------------------------------------------------------------
The agent and the finalizer write to the same container stderr, and the agent is
a language model that can be induced to print anything. So a line that LOOKS
like a finalizer verdict is not proof that the finalizer produced it: an agent
that prints the success line verbatim would be believed.

Three things follow, and they are the design rather than caveats:

1. Patterns are anchored to a full-line grammar, so incidental prose that merely
   mentions the phrase does not match. This raises the bar from "accidental" to
   "deliberate", which is worth doing and is not a security boundary.
2. Nothing captured from the stream is ever persisted. Reasons are built from
   fixed templates and whitelisted numeric fields, so a credential printed on
   the stream cannot be lifted into a stored record.
3. Counters are read ONLY from the selected verdict line, never from the stream
   at large, so an earlier unrelated `accepted=999` cannot displace the truth.

The real fix is a channel the agent cannot write to: the finalizer should write
its result to a file under the host-backed workspace directory, which Syn137
already collects. Then this parser becomes a fallback for old images rather than
the source of truth. Tracked as the follow-up to this module, and the reason
`CaptureState.UNKNOWN` exists rather than defaulting to optimism.
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

# COMPLETE line grammars, matched with fullmatch. Anchoring only the start was
# not enough: `[finalize] session-store upload complete (` - a truncated line
# with no counters and no closing paren - matched and returned CAPTURED. A
# malformed verdict must be UNKNOWN, not success.
#
# Each pattern below mirrors one terminal `echo` in finalize.sh. The trailing
# `.*` after the stable part covers the spool-path clause, whose value varies
# per workspace; everything BEFORE it is required structure.
_LINE = r"\[finalize\] session-store "

#: `upload complete (<counters>); spool retained at <dir>`
#: The counter list is required and must be closed. A verdict with no counters
#: is not a verdict.
_RE_COMPLETE = re.compile(_LINE + r"upload complete \([^)]*\);.*")

#: `upload TIMED OUT after <n>s; spool retained at <dir>`
_RE_TIMEOUT = re.compile(_LINE + r"upload TIMED OUT after (\d+)s;.*")

#: `upload FAILED (rc=<n>); spool retained at <dir>`
_RE_FAILED = re.compile(_LINE + r"upload FAILED \(rc=(\d+)\);.*")

#: Two forms, both closing the parenthesis before the colon:
#:   `sweep INCOMPLETE (<counters>): at least one transcript ...`
#:   `sweep INCOMPLETE (unresolved rejection recorded at <path>): ...`
_RE_INCOMPLETE = re.compile(_LINE + r"sweep INCOMPLETE \([^)]*\):.*")

#: `sweep produced no parseable summary line; treating as INCOMPLETE ...`
_RE_UNPARSEABLE = re.compile(_LINE + r"sweep produced no parseable summary line;.*")

#: Counters the exporter prints on its summary line. Declared here so the names
#: this side reads are spelled once.
# All eight the exporter's summary line carries (finalize.sh:448). `rejected`
# and `skipped_oversize` were missing, which are the two that distinguish "the
# store refused it" from "we never sent it" - exactly the counters an operator
# needs when something did not land.
_COUNTERS = (
    "discovered",
    "skipped_unchanged",
    "uploaded",
    "accepted",
    "duplicate",
    "rejected",
    "skipped_oversize",
    "failed",
)


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


def _counters_from(verdict_line: str) -> dict[str, int]:
    """Whitelisted ``name=<digits>`` pairs, from the VERDICT LINE only.

    Deliberately not from the stream at large. Searching everything meant an
    unrelated earlier ``accepted=999`` anywhere in the agent's output would be
    taken as the truth, because the first match won. Only the line that produced
    the verdict can describe that verdict.

    Values are ints by construction: the pattern admits digits and the result is
    parsed, so nothing from the stream is stored as text.
    """
    found: dict[str, int] = {}
    for name in _COUNTERS:
        m = re.search(rf"\b{name}=(\d+)\b", verdict_line)
        if m:
            found[name] = int(m.group(1))
    return found


def _classify(line: str) -> CaptureOutcome | None:
    """One finalizer line to an outcome, or None if it is not a verdict.

    Split out from parse_capture_status so neither function carries both the
    line-selection policy and the whole verdict decision table; together they
    exceeded the cyclomatic budget.
    """
    counters = _counters_from(line)

    if _RE_COMPLETE.fullmatch(line):
        return CaptureOutcome(state=CaptureState.CAPTURED, counters=counters)

    if m := _RE_TIMEOUT.fullmatch(line):
        return CaptureOutcome(
            state=CaptureState.FAILED,
            reason=f"upload timed out after {m.group(1)}s",
            counters=counters,
        )

    if m := _RE_FAILED.fullmatch(line):
        return CaptureOutcome(
            state=CaptureState.FAILED,
            reason=f"exporter exited {m.group(1)}",
            counters=counters,
        )

    if _RE_INCOMPLETE.fullmatch(line):
        # The reason is REBUILT from whitelisted numeric fields, never copied
        # from the line. The finalizer puts free text in those parentheses, and
        # this field is persisted and displayed: an exporter build that printed
        # an auth header would otherwise have it lifted into a durable record.
        blocking = {
            k: v
            for k, v in counters.items()
            if k in ("failed", "rejected", "skipped_oversize") and v
        }
        detail = ", ".join(f"{k}={v}" for k, v in sorted(blocking.items()))
        return CaptureOutcome(
            state=CaptureState.INCOMPLETE,
            reason=f"sweep incomplete ({detail})" if detail else "sweep incomplete",
            counters=counters,
        )

    if _RE_UNPARSEABLE.fullmatch(line):
        return CaptureOutcome(
            state=CaptureState.UNKNOWN,
            reason="the exporter produced no parseable summary line",
            counters=counters,
        )

    return None


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

    # Last line wins: the finalizer's terminal verdict is its final word.
    for line in reversed(lines):
        if outcome := _classify(line):
            return outcome

    # Lines carrying the prefix but no recognised verdict. Counters are left
    # empty on purpose: without a verdict line to read them from, any number on
    # the stream is unattributed, and an unattributed count is worse than none.
    return CaptureOutcome(
        state=CaptureState.UNKNOWN,
        reason="the finalizer reported, but in a form this parser does not recognise",
    )
