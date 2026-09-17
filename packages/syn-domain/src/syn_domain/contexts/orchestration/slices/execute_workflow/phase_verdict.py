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

THEN AGAIN, IN THE FIXES. Four defects, one shape: what the report MEANT
changed with what the surrounding text happened to contain - and (4) says the
shape survives being fixed HERE, because the text can be thrown away before it
ever reaches this module.

  1. FAILURE became completed - a brace inside ``comments``, above.
  2. SUCCESS became UNREADABLE - the block was located with ``rfind``, the
     textually LAST marker, so a report whose own ``comments`` mention
     ``TASK_RESULT:`` was read from the mention inside its own string.
  3. SUCCESS became FAILURE - the reader then took the last DECODABLE
     candidate, so a genuine report followed by anything JSON-shaped lost to
     it. The literal failure example lives in the prompt every phase is sent,
     so an agent that reports success and then explains the reporting format
     reported failure.

  4. FAILURE became completed again, one hop upstream - the defect this
     module was written for, arriving by a route the module could not see. A
     processor reduced the whole stream to a single mutable "last message"
     BEFORE any of this ran, so a complete, correctly terminated failure
     report followed by one more assistant turn - "done", a sign-off, anything
     at all - was overwritten and never parsed. The phase read NOT_REPORTED,
     which does not refuse, and completed.

Each fix moved the same guess - WHERE IS THE PAYLOAD IN THIS PROSE - rather
than removing it. First, last and nearest-marker all fail for one reason: the
text legitimately contains things that look exactly like the payload, and no
amount of looking can tell a report from a quotation of one.

SO THE PAYLOAD IS DELIMITED, NOT LOCATED. A report is
``TASK_RESULT:``, one JSON value, and ``TASK_RESULT_END``; anything missing the
terminator is prose about a report, whatever it looks like. Which text is the
report therefore has one answer given by structure, and it does not depend on
what else the message says, in what order, or how JSON-shaped it is.

AND A REPORT IS READ WHEN IT ARRIVES, NOT WHEN THE STREAM ENDS. That is what
(4) costs to close: nothing may hold the agent's words waiting to be parsed,
because whatever holds them can be overwritten. `VerdictReader` is fed each
message as the processor sees it, so a report that has been read is already a
verdict and there is no longer any text for a later turn to replace.

WHAT TWO REPORTS MEAN, DECIDED RATHER THAN LEFT OPEN. A REFUSAL IS FINAL: once
a message has been read as FAILURE or UNREADABLE, nothing said afterwards
takes it back. A message carrying no report changes nothing, and otherwise the
later report stands.

That is chosen over "first wins" and over "last wins" because it is the only
one of the three whose answer does not depend on the order the reports arrived
in: success-then-failure and failure-then-success both refuse. Ordering is
evidence about text, and every defect above came from trusting it. It is also
the fail-closed direction - the cost of being wrong is a rerun, and the cost of
the other direction is the completed failure this module exists to stop.

The rule holds per REPORT, not per message, so it settles two blocks in one
message and two messages with one block each identically; an agent cannot
change what it reported by choosing where to put the newline.

WHAT THE EMITTER MUST GUARANTEE, because a parser contract the producer does
not honour is not a fix. `render_workspace_prompt` must (a) instruct the
terminator and (b) contain no complete block of its own, so that quoting the
instructions can never be mistaken for obeying them. (b) is pinned by test, not
by care: `test_reported_failure_stays_a_failure.py` reads the rendered prompt
with this module and requires NOT_REPORTED.

THE PRICE, STATED. A block written without its terminator is UNREADABLE, which
refuses completion. That is the fail-closed direction and it is the whole cost
of the scheme: an agent that ignores the contract costs a rerun, and never a
false completion. What is no longer bought with it is the old blanket refusal
whenever the marker appeared after a report - that refused real successes,
which is defect 2 again in a wider spelling.

WHAT IS AND IS NOT A VERDICT. Four states, and the distinction between the last
two is the whole point:

  ``SUCCESS``       the agent reported success
  ``FAILURE``       the agent reported failure - the phase must not complete
  ``UNREADABLE``    the agent wrote the marker and we could not read a
                    terminated verdict under it. Absence of a verdict is NOT a
                    verdict: this refuses completion, because the alternative
                    is discarding what may have been a failure report
  ``NOT_REPORTED``  no marker was written at all. The agent made no claim about
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
what lets the delimiters, the JSON shape and the strictness about ``success``
all change without touching a stream processor or the dispatcher.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum, auto
from typing import Final

__all__ = [
    "TASK_RESULT_MARKER",
    "TASK_RESULT_TERMINATOR",
    "AgentVerdict",
    "VerdictReader",
    "VerdictStatus",
]

#: The token a phase's prompt tells it to write before its result JSON.
#: OUR convention, not a harness format - which is why every harness's
#: processor can read it with the same code.
TASK_RESULT_MARKER: Final[str] = "TASK_RESULT:"

#: The token that CLOSES the block, and the entire reason a report can be told
#: apart from a quotation of one. It is not decoration on the marker: without
#: it there is no answer to "which of these is the report" that some legal
#: message does not contradict - see the defects in the module docstring.
TASK_RESULT_TERMINATOR: Final[str] = "TASK_RESULT_END"


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
        """Read the phase's own verdict out of the report(s) its agent wrote.

        WHICH parts of the text are reports is `_delimited_reports`'s question;
        this one decides what each of them SAYS and, when they disagree, which
        stands. A verdict is a JSON object whose ``success`` is a JSON boolean,
        and anything the agent wrote in its place is unreadable rather than a
        pass.

        One message is one reading, not the whole phase: use `VerdictReader`
        when the messages arrive one at a time, so that a report already read
        cannot be undone by the next one.
        """
        verdict = cls.not_reported()
        if not text:
            return verdict
        for report in _delimited_reports(text):
            verdict = _settle(verdict, cls._from_report(report))
        return verdict

    @classmethod
    def _from_report(cls, report: _Report) -> AgentVerdict:
        """What one delimited block claims, judged on its own."""
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
                f"Phase '{phase_id}' wrote a {TASK_RESULT_MARKER} marker whose block "
                f"could not be read as a verdict - it is not JSON, or it is not "
                f'closed by a {TASK_RESULT_TERMINATOR} line: "{self.comments}". An '
                f"unreadable report may be a failure report, so the phase fails "
                f"rather than completing on a verdict nobody could read."
            )
        return ""


class VerdictReader:
    """The phase's verdict, accumulated from its agent's messages as they arrive.

    The caller feeds every message it sees and asks, at the end, what the
    phase claimed. It never learns which message the answer came from, whether
    any message held more than one report, or how a disagreement was settled -
    which is what lets the policy in this module's docstring change without
    touching a stream processor.

    Feeding the same message twice is safe and means nothing new: the harnesses
    repeat the final assistant text on their terminal line, and a report read
    twice agrees with itself.
    """

    def __init__(self) -> None:
        self._verdict = AgentVerdict.not_reported()

    def read(self, message: str | None) -> None:
        """Take whatever verdict ``message`` carries, if it may still change one."""
        self._verdict = _settle(self._verdict, AgentVerdict.from_agent_text(message))

    @property
    def verdict(self) -> AgentVerdict:
        """What the phase has claimed about itself so far."""
        return self._verdict


def _settle(earlier: AgentVerdict, later: AgentVerdict) -> AgentVerdict:
    """Which of two verdicts from the same phase stands. See the module docstring.

    Stated once, here, because both readings go through it: folding the reports
    inside one message, and folding one message into a whole stream. Those give
    the same answer for the same reports however they were split up, which is
    the property that stops a message boundary being somewhere a verdict can
    hide.
    """
    if later.status is VerdictStatus.NOT_REPORTED:
        return earlier
    if earlier.refuses_completion:
        return earlier
    return later


@dataclass(frozen=True)
class _Report:
    """The text of one report, and the JSON value that text carried.

    ``decoded`` is None when the message held a marker but no complete block
    under it - the payload is then the text an operator needs to see to work
    out what the agent wrote instead.
    """

    payload: str
    decoded: object | None


def _payload_starts(text: str, after: int) -> int:
    """Where the value begins, skipping the whitespace a writer put in."""
    while after < len(text) and text[after].isspace():
        after += 1
    return after


def _delimited_reports(text: str) -> list[_Report]:
    """Every report ``text`` contains, in the order written. Empty means none.

    A REPORT IS THE THREE PARTS TOGETHER: the marker, one JSON value that
    `raw_decode` says where to end, and `TASK_RESULT_TERMINATOR` after it
    separated by nothing but whitespace. Every other marker occurrence is
    prose - a quotation, an explanation, a half-written block - and prose has
    no verdict in it, wherever it sits and however much it looks like one.
    That is what makes this immune to the message containing the marker, a
    brace, a nested object, or the prompt's own failure example, before or
    after a genuine report.

    Two blocks correctly written means the agent reported twice, and BOTH are
    returned: which one stands is `_settle`'s decision, not this function's,
    and it is the same decision whether the second block arrived in this text
    or in a later message. Picking a winner here is what made that untrue.

    A marker with no complete block anywhere yields one `_Report` that cannot
    decode, so it reads as UNREADABLE and refuses completion. Silence and a
    botched report are different facts and only the second is fatal. An
    unclosed block alongside a closed one is prose and is dropped - see
    `test_a_truncated_second_block_does_not_unmake_a_closed_first_one`.
    """
    decoder = json.JSONDecoder()
    reports: list[_Report] = []
    unclosed_at: int | None = None
    search_from = 0
    while (marker_at := text.find(TASK_RESULT_MARKER, search_from)) != -1:
        payload_at = _payload_starts(text, marker_at + len(TASK_RESULT_MARKER))
        try:
            decoded, payload_ends = decoder.raw_decode(text, payload_at)
        except ValueError:
            # No value here to delimit, so resume just past the marker rather
            # than skipping over text this never read.
            unclosed_at = payload_at
            search_from = payload_at
            continue
        if not text.startswith(TASK_RESULT_TERMINATOR, _payload_starts(text, payload_ends)):
            unclosed_at = payload_at
            search_from = payload_ends
            continue
        reports.append(_Report(payload=text[payload_at:payload_ends], decoded=decoded))
        search_from = payload_ends + len(TASK_RESULT_TERMINATOR)
    if reports:
        return reports
    if unclosed_at is None:
        return []
    return [_Report(payload=text[unclosed_at:], decoded=None)]


def _excerpt(raw: str) -> str:
    """The unreadable text, short enough to sit in an error message."""
    flattened = " ".join(raw.split())
    return flattened if len(flattened) <= 200 else f"{flattened[:200]}…"
