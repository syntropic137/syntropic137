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
        """Read the phase's own verdict out of the last thing its agent said.

        The block is parsed as JSON from the marker onwards with
        `raw_decode`, which stops at the end of the JSON VALUE. A brace inside
        a string is therefore part of the string, and prose after the block is
        ignored - both of which the old scan-to-the-first-``}`` could not do.
        The LAST marker wins: a prompt that quotes the contract, or an agent
        that shows an example before committing to one, must not outvote the
        agent's final word.
        """
        if not text or TASK_RESULT_MARKER not in text:
            return cls.not_reported()
        raw = text[text.rfind(TASK_RESULT_MARKER) + len(TASK_RESULT_MARKER) :].strip()
        try:
            reported, _ = json.JSONDecoder().raw_decode(raw)
        except ValueError:
            return cls(VerdictStatus.UNREADABLE, _excerpt(raw))
        if not isinstance(reported, dict):
            return cls(VerdictStatus.UNREADABLE, _excerpt(raw))
        claim = reported.get("success")
        comments = reported.get("comments")
        said = str(comments) if comments is not None else ""
        # A JSON boolean or nothing. `"success": "false"` is a string, and a
        # string is truthy, so anything looser here would read a reported
        # FAILURE as a pass - the exact direction this module exists to close.
        if not isinstance(claim, bool):
            return cls(VerdictStatus.UNREADABLE, _excerpt(raw))
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


def _excerpt(raw: str) -> str:
    """The unreadable text, short enough to sit in an error message."""
    flattened = " ".join(raw.split())
    return flattened if len(flattened) <= 200 else f"{flattened[:200]}…"
