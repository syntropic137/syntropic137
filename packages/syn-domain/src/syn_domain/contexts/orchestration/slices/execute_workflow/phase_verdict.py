"""What a phase said about its own outcome, and what that obliges the caller to do.

THE FAILURE THIS EXISTS TO STOP (#1256). Every phase prompt ends with a
mandatory block - ``TASK_RESULT: {"success": ..., "comments": ...}`` - which is
how a phase reports that it could NOT do what it was asked. That report could
be turned into a completed phase two ways at once:

  - the block was located by scanning forward to the first ``}``, so a legal
    JSON string value containing a brace ("the handler returns dict{} not a
    model") truncated the text mid-string, `json.loads` raised, and the verdict
    was swallowed by an `except` that returned None;
  - nothing downstream read the parsed result at all. It reached
    `StreamResult.agent_task_result` and stopped there, so even a perfectly
    parsed ``success: false`` completed the phase.

The second is why the first survived: a value nobody consumes cannot be
observed to be wrong.

AND THE MIRROR OF IT, in the first fix for the above. Both defects are one
shape: what the report MEANT changed with what its strings happened to
contain. The fix reproduced that shape at the other end. It located the block
with ``rfind``, i.e. the textually LAST marker, so a report whose own
``comments`` mention ``TASK_RESULT:`` was read starting from the mention
inside its own string, decoded to nothing, and a reported SUCCESS became a
refusal. That input is not exotic: it is what any agent explaining result
parsing writes, and therefore precisely what an agent working on THIS module
produces - the defect fired hardest on the runs discussing it.

So the invariant is symmetric, and neither half may be bought with the other:
READING A RESULT MUST BE ROBUST TO THE RESULT'S OWN VOCABULARY APPEARING
INSIDE ITS STRING VALUES. A failure must never become a completed phase, and
a success must never become a failure because its text mentioned the marker.
`_last_report` is where that is enforced, and it holds the second half without
spending the first - an unreadable FINAL block is still unreadable.

WHAT IS AND IS NOT A VERDICT. Four states, and the distinction between the last
two is the whole point:

  ``SUCCESS``       the agent reported success
  ``FAILURE``       the agent reported failure - the phase must not complete
  ``UNREADABLE``    the agent wrote the block and we could not read it. Absence
                    of a verdict is NOT a verdict: this refuses completion,
                    because the alternative is discarding what may have been a
                    failure report
  ``NOT_REPORTED``  no block was written at all. The agent made no claim about
                    itself, which is a different fact from an unreadable claim
                    and is deliberately NOT fatal here - see the limit below

THE LIMIT, STATED. ``NOT_REPORTED`` does not refuse completion. A phase whose
agent never emits the block is left to the checks that already govern it: the
exit status, the declared-output rule (#1167) and the empty-artifact rule
(#1195). Making silence fatal is a change to what the platform REQUIRES of
every agent on every harness, not a fix to a report being discarded, and it
would land first on the harness that has no verdict to give. It belongs in its
own change, with its own evidence about how often live phases omit the block.

WHY A MODULE AND NOT A PARSER FUNCTION. The caller asks one question - "may
this phase complete?" - and never learns how the answer was reached. That is
what lets the marker, the JSON shape and the strictness about ``success`` all
change without touching a stream processor or the dispatcher.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum, auto
from typing import Final

__all__ = [
    "TASK_RESULT_MARKER",
    "AgentVerdict",
    "VerdictStatus",
]

#: The token a phase's prompt tells it to write before its result JSON.
#: OUR convention, not a harness format - which is why every harness's
#: processor can read it with the same code.
TASK_RESULT_MARKER: Final[str] = "TASK_RESULT:"


class VerdictStatus(Enum):
    """Whether the phase claimed an outcome, and whether the claim was readable."""

    NOT_REPORTED = auto()
    SUCCESS = auto()
    FAILURE = auto()
    UNREADABLE = auto()


@dataclass(frozen=True)
class AgentVerdict:
    """The phase's claim about itself, already judged.

    ``comments`` is what the agent wrote alongside a readable verdict, and the
    unparsed text it wrote when the verdict was not readable - in both cases
    the thing an operator needs to see, which is why one field carries both
    rather than the caller having to know which to look at.
    """

    status: VerdictStatus
    comments: str = ""

    @classmethod
    def not_reported(cls) -> AgentVerdict:
        """The verdict of a phase that made no claim about itself."""
        return cls(VerdictStatus.NOT_REPORTED)

    @classmethod
    def from_agent_text(cls, text: str | None) -> AgentVerdict:
        """Read the phase's own verdict out of the last report its agent wrote.

        WHICH text is the report is `_last_report`'s question; this one
        decides only what that report SAYS. A verdict is a JSON object whose
        ``success`` is a JSON boolean, and anything the agent wrote in its
        place is unreadable rather than a pass.
        """
        if not text:
            return cls.not_reported()
        report = _last_report(text)
        if report is None:
            return cls.not_reported()
        reported = report.decoded
        if not isinstance(reported, dict):
            return cls(VerdictStatus.UNREADABLE, _excerpt(report.payload))
        claim: object = reported.get("success")
        comments: object = reported.get("comments")
        said = str(comments) if comments is not None else ""
        # A JSON boolean or nothing. `"success": "false"` is a string, and a
        # string is truthy, so anything looser here would read a reported
        # FAILURE as a pass - the exact direction this module exists to close.
        if not isinstance(claim, bool):
            return cls(VerdictStatus.UNREADABLE, _excerpt(report.payload))
        return cls(VerdictStatus.SUCCESS if claim else VerdictStatus.FAILURE, said)

    @property
    def refuses_completion(self) -> bool:
        """True when this phase must not be recorded as completed."""
        return self.status in (VerdictStatus.FAILURE, VerdictStatus.UNREADABLE)

    def refusal(self, *, phase_id: str) -> str:
        """Why the phase may not complete, in the words an operator needs.

        Only meaningful when `refuses_completion` is true; a caller that asks
        anyway gets the empty string rather than an exception, because a
        message is never the thing a decision should hinge on.
        """
        if self.status is VerdictStatus.FAILURE:
            return (
                f"Phase '{phase_id}' REPORTED FAILURE. Its agent ended with "
                f'TASK_RESULT success=false: "{self.comments}". The phase is failed '
                f"on its own report rather than completed on its exit status."
            )
        if self.status is VerdictStatus.UNREADABLE:
            return (
                f"Phase '{phase_id}' wrote a TASK_RESULT block that could not be "
                f'read as a verdict: "{self.comments}". An unreadable report may be '
                f"a failure report, so the phase fails rather than completing on a "
                f"verdict nobody could read."
            )
        return ""


@dataclass(frozen=True)
class _Report:
    """The text of one report, and the JSON value that text began with.

    ``decoded`` is None when it began with no JSON value at all, which is
    indistinguishable here from a literal ``null`` and, either way, is not a
    verdict.
    """

    payload: str
    decoded: object | None


def _last_report(text: str) -> _Report | None:
    """The last thing in ``text`` that is a report, not a mention of one.

    THE DECISION, since two readings of "last" were available. Scanning
    forward and letting `raw_decode` say where each report ENDS delimits it,
    and a marker inside the span of a report already read is that report's own
    string content - never a candidate to be the next report. Taking the
    textually last marker instead cannot tell a report from a quotation of
    one, and gets it wrong exactly when an agent writes about result parsing.
    Delimiting is what makes "last" unambiguous, so this does not choose
    between the task's two options; the first is only correct because of the
    second.

    The last CANDIDATE decides, readable or not. That is the half that must
    not be traded away to fix the above: an agent that restates its result has
    stated it last, so a later real block still outvotes an earlier one, and a
    final block nobody can read stays unreadable rather than quietly resolving
    to some earlier block's success. Returns None when the marker never
    appears at all, which is silence and not a verdict.
    """
    decoder = json.JSONDecoder()
    latest: _Report | None = None
    search_from = 0
    while (marker_at := text.find(TASK_RESULT_MARKER, search_from)) != -1:
        payload_at = marker_at + len(TASK_RESULT_MARKER)
        while payload_at < len(text) and text[payload_at].isspace():
            payload_at += 1
        try:
            decoded, report_ends = decoder.raw_decode(text, payload_at)
        except ValueError:
            # Nothing delimits a payload that is not a JSON value, so the
            # excerpt is the rest of the text, and the scan resumes just after
            # the marker rather than skipping over content it never read.
            latest = _Report(payload=text[payload_at:], decoded=None)
            search_from = payload_at
        else:
            latest = _Report(payload=text[payload_at:report_ends], decoded=decoded)
            search_from = report_ends
    return latest


def _excerpt(raw: str) -> str:
    """The unreadable text, short enough to sit in an error message."""
    flattened = " ".join(raw.split())
    return flattened if len(flattened) <= 200 else f"{flattened[:200]}…"
