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

THEN TWICE MORE IN THE FIXES, AND ONCE ABOVE THEM. Four defects, one shape:
what the report MEANT changed with what the surrounding text happened to
contain. (4) is the one that says the shape survives being fixed HERE - the
text can be thrown away before it ever reaches this module.

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

WHAT TWO REPORTS MEAN, DECIDED RATHER THAN LEFT OPEN. THE STRONGEST CLAIM IN
THE STREAM STANDS, on this precedence and never on which arrived first:

    FAILURE  >  SUCCESS  >  UNREADABLE  >  NOT_REPORTED

So a reported failure is not taken back by a later success, a closed report
beats an unclosed marker wherever either sits, and a message carrying no report
changes nothing.

Chosen over "first wins" and "last wins" because neither of those consults
anything but order, and order is a property of the TEXT - which is what every
defect above came from trusting. A precedence is commutative: the same reports
settle the same way however they are shuffled, so no agent can change what it
reported by reordering or re-splitting its own output. It also runs
fail-closed, and the two directions cost very differently: being wrong here
costs a rerun, being wrong the other way is the completed failure this module
exists to stop.

The two middle steps are not decoration, and each was a live defect caught by
test. SUCCESS > UNREADABLE is defect (3) at stream scale: an agent that
mentions ``TASK_RESULT:`` mid-run and then reports success cleanly must not be
refused for the mention, exactly as an unclosed block beside a closed one is
already prose within a single message. FAILURE > SUCCESS is defect (1) at
stream scale, in the direction that matters.

The rule holds per REPORT, not per message, so two blocks in one message and
two messages of one block each settle identically. Among equal claims the later
wording stands - the agent restating itself is still the agent, and nothing
about the decision turns on it.

THE PRICE OF THIS ONE, ALSO STATED. A phase that writes the marker without a
readable block and then never reports at all is UNREADABLE and refuses, where
before only its FINAL message was ever examined and an intervening "done" hid
it. That is a botched report being seen rather than a new rule; the phase that
reports properly is unaffected whenever it reports.

WHAT THE EMITTER MUST GUARANTEE, because a parser contract the producer does
not honour is not a fix. `render_workspace_prompt` must (a) instruct the
terminator and (b) hand out blocks that are copyable VERBATIM - marker, literal
JSON and terminator in one fence - because an example an agent has to edit is an
example it can get wrong, which is #1324.

(b) used to read "contain no complete block of its own". That was stronger and
it is no longer available: a fence copyable verbatim is byte-identical to a
report, and this reader is delimited rather than located, so quoting and obeying
are the same bytes and nothing can separate them. What survives is the half that
matters, pinned by test rather than by care - THE PROMPT CAN NEVER MANUFACTURE A
COMPLETION. Reading the rendered prompt with this module yields FAILURE, never
SUCCESS, because the precedence below makes the prompt's own failure example the
strongest claim in it. So quoting the instructions moves a verdict only toward
refusal, which costs a rerun, and never toward the completed failure this module
exists to stop. See `workspace_prompt`'s docstring for why that trade is the
cheaper one.

THE PRICE, STATED. A block written without its terminator is UNREADABLE, which
refuses completion. That is the fail-closed direction and it is the whole cost
of the scheme: an agent that ignores the contract costs a rerun, and never a
false completion. What is no longer bought with it is the old blanket refusal
whenever the marker appeared after a report - that refused real successes,
which is defect 2 again in a wider spelling.

THE ONE SHAPE READ THAT THE CONTRACT DOES NOT DESCRIBE (#1324). An agent that
finished its work and then invented its own result schema - ``{"status":
"completed", "branch": ..., "commit": ..., "pr": 1371}`` - reported nothing this
module could read, and exec-cd5e75eaeb63 lost a $10.76 phase whose commit was
already pushed. Every failing block observed after #1327 made the copyable fence
literal had that one defect and no other: the key was spelled ``status``, with
``completed`` or ``failed`` under it.

So that exact shape is read as the verdict it plainly states, and nothing around
it is: NO ``success`` key present, and ``status`` a JSON string that is EXACTLY
``completed`` or ``failed``. ``Completed``, ``done``, a non-string ``status``, or
a ``status`` beside an unreadable ``success`` remain UNREADABLE precisely as
before.

AND THE CONTRACT IS ASKED FIRST, SO THE ALIAS ONLY EVER ADDS A READING. A
``success`` that is a JSON boolean IS the verdict, and a ``status`` beside it is
an extra key exactly as every other extra key is: ignored, unweighed, and unable
to move the outcome in either direction. ``{"success": true, "status": "failed"}``
completes the phase and ``{"success": false, "status": "completed"}`` refuses it,
both precisely as they did before the alias existed.

That is not indifference to a block that says two things; it is what stops the
alias becoming a second contract. Weighing the two keys against each other -
refusing the block whose ``status`` disagrees - reads as caution and is not: it
would let a key the prompt tells agents NEVER to write refuse a phase that wrote
the contract's key correctly, which is defect (2) below in a new spelling, and
it would do it on the strength of a word this module would otherwise never have
looked at. The alias reads blocks that say nothing under ``success``. Where
``success`` speaks there is nothing for it to do, and a rule about the two keys
together is a rule about a question neither of them asked.

WHICH LEAVES ONE WAY A BLOCK CAN STILL NAME ITS OUTCOME TWICE - under the SAME
key. ``{"status": "failed", "status": "completed"}`` is legal JSON, and a JSON
decoder keeps the LAST of duplicate members, so the failure the agent wrote is
deleted by the parser before anything here sees the value. Read off the survivor
that block COMPLETES a phase that plainly stated failure, and swapping the two
members swaps the verdict: the outcome is settled by the order of two identical
keys, which is the TEXT deciding what a report means - defect (1) above,
arriving through the alias. So the duplication is read off the member list while
it still exists, in `_decode_payload`, and a repeated ``status`` is UNREADABLE.
A repeated ``success`` is deliberately left alone: it reads today exactly as it
reads on the contract path and the alias did not change it, so making it fatal
is a new strictness on the contract itself rather than a repair to this.

WHY THIS IS NOT THE COERCION THE STRICT MODEL EXISTS TO REFUSE - the first
objection to raise, and the one that decides whether the alias may exist at all.
`_ReportedResult` refuses ``"success": "true"`` because reading a STRING as a
BOOLEAN is a guess about a value nobody wrote: ``"true"`` is equally the start of
``"true, but the tests fail"``, and the guess resolves it in the completing
direction. The alias guesses nothing. It is a closed two-element map from whole
string literals to the outcomes they name, carrying BOTH directions - ``failed``
refuses the phase exactly as ``success: false`` does - and it applies only where
the contract's own key is ABSENT, so it can never overrule, soften or contradict
anything the agent did write. A permissive mode would widen what a value may
MEAN; this widens only which key the same two meanings may be written under.

AND IT IS RECORDED RATHER THAN ABSORBED. Reading the alias logs a warning naming
the spelling and the payload, and the verdict carries ``via_status_alias`` so a
refusal states how the phase reported itself instead of quoting a
``success=false`` nobody wrote. An alias nobody can see is how drift becomes the
format: the contract is still one key called ``success``, and
`render_workspace_prompt` now says that in as many words rather than leaving it
to be inferred from an example.

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
import logging
import re
from dataclasses import dataclass
from enum import Enum, StrEnum, auto
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
)

logger = logging.getLogger(__name__)

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

#: A markdown code fence an agent wraps the block's JSON in (#1324).
#:
#: Agents summarise in markdown, and some write the report as
#: ``TASK_RESULT:`` + a ```json fence + the object + a closing fence +
#: ``TASK_RESULT_END``. The JSON inside is exactly the value the grammar asks
#: for; only the fence is extra, so unwrapping it adds no interpretation. It is
#: accepted only as a PAIR around the one value - an opening fence with no
#: closing one is still an unclosed block - and its use is logged so the drift
#: stays visible rather than silently absorbed. Seen in production on
#: exec-297778171fa2, which finished its work, pushed it, and was failed on
#: ```json { "success": true, ... }.
_CODE_FENCE: Final[str] = "```"
_OPENING_FENCE: Final[re.Pattern[str]] = re.compile(r"```[A-Za-z0-9_+-]*")


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

    ``via_status_alias`` says the claim was written as ``"status"`` rather than
    as the ``"success"`` boolean the contract asks for (#1324). It is read in
    exactly one place - `refusal`, so that the line an operator greps for
    quotes what the agent actually wrote - and it exists because an alias that
    leaves no trace in the outcome is indistinguishable from the format having
    quietly changed.
    """

    status: VerdictStatus
    comments: str = ""
    via_status_alias: bool = False

    @classmethod
    def not_reported(cls) -> AgentVerdict:
        """The verdict of a phase that made no claim about itself."""
        return cls(VerdictStatus.NOT_REPORTED)

    @classmethod
    def from_agent_text(cls, text: str | None) -> AgentVerdict:
        """Read the phase's own verdict out of the report(s) its agent wrote.

        WHICH parts of the text are reports is `_delimited_reports`'s question;
        this one decides what each of them SAYS and, when they disagree, which
        stands. A verdict is a JSON object whose ``success`` is a JSON boolean -
        or, for the one shape agents demonstrably write instead, whose ``status``
        is exactly ``completed`` or ``failed`` with no ``success`` beside it
        (#1324). Anything else the agent wrote in its place is unreadable rather
        than a pass.

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
        """What one delimited block claims, judged on its own.

        THE CONTRACT ANSWERS ALONE WHENEVER IT CAN, and the order of these two
        readings is the whole of that rule. A ``success`` the agent wrote as a
        JSON boolean settles the block here and returns; the alias is reached
        only where the contract found nothing it could read. So ``status`` can
        never overrule, soften or contradict what was written under the key the
        contract actually asks for - it is an extra key beside a readable
        ``success``, as it was before the alias existed and as it still is on
        `main`.
        """
        try:
            reported = _ReportedResult.model_validate(report.decoded)
        except ValidationError:
            return cls._from_status_alias(report)
        return cls(
            VerdictStatus.SUCCESS if reported.success else VerdictStatus.FAILURE,
            reported.said,
        )

    @classmethod
    def _from_status_alias(cls, report: _Report) -> AgentVerdict:
        """What a block that named its outcome ``status`` claims (#1324).

        Reached only after the contract above was not met, which is what keeps
        the alias unable to overrule a ``success`` the agent did write. A block
        whose ``success`` is a readable boolean has already been settled there;
        what arrives here either wrote no ``success`` at all or wrote one the
        contract could not read, and the second is refused here rather than
        rescued off its ``status``.

        A ``status`` written TWICE is refused before it is read, because by the
        time a model could look there is only one of them left - see
        `_decode_payload` for why the answer travels on the `_Report` rather
        than being derived from the value here.
        """
        if report.repeats_status:
            logger.warning(
                'TASK_RESULT block wrote "%s" more than once, so which outcome it states '
                "depends only on which duplicate the JSON decoder kept. The phase is "
                "refused rather than read off the survivor (#1324): %s",
                _ALIAS_KEY,
                _excerpt(report.payload),
            )
            return cls(VerdictStatus.UNREADABLE, _excerpt(report.payload))
        try:
            aliased = _StatusAliasResult.model_validate(report.decoded)
        except ValidationError:
            return cls(VerdictStatus.UNREADABLE, _excerpt(report.payload))
        logger.warning(
            'TASK_RESULT block named its outcome "status": "%s" instead of writing a '
            '"success" boolean, and was read as %s under the #1324 alias. The phase '
            "is not following the reporting contract: %s",
            aliased.status.value,
            aliased.status.verdict.name,
            _excerpt(report.payload),
        )
        return cls(aliased.status.verdict, aliased.said, via_status_alias=True)

    @property
    def refuses_completion(self) -> bool:
        """True when this phase must not be recorded as completed."""
        return self.status in (VerdictStatus.FAILURE, VerdictStatus.UNREADABLE)

    @property
    def failure_classification(self) -> FailureClassification:
        """What a failure ended by this verdict IS, for the run's tally (#1357).

        THE FACT THAT ONLY EXISTS HERE. By the time a failure reaches the
        aggregate it is an exception and a string, and every one of them reads
        `failed`; this is the last frame that still knows the phase ended on
        its OWN readable report rather than on an exit status, a timeout or a
        crash. A tally that cannot make that distinction counts the quality
        gate doing its job as the platform breaking.

        UNREADABLE IS NOT A CORRECT REFUSAL, and that is the one line worth
        arguing. A block nobody could parse might have been a refusal, and it
        refuses completion for exactly that reason - but "might have been" is
        not evidence the system worked, and the botched block is itself
        something that went wrong. So it classifies as `PLATFORM`, in the same
        fail-closed direction the rest of this module runs in: being wrong
        this way overstates our own failures, and being wrong the other way
        credits us with a refusal nobody can read.

        The non-refusing states never reach a failure and answer `PLATFORM`
        for the same reason `refusal` answers "": a caller that asks anyway
        gets the conservative answer rather than an exception.
        """
        if self.status is VerdictStatus.FAILURE:
            return FailureClassification.CORRECT_REFUSAL
        return FailureClassification.PLATFORM

    def refusal(self, *, phase_id: str) -> str:
        """Why the phase may not complete, in the words an operator needs.

        Only meaningful when `refuses_completion` is true; a caller that asks
        anyway gets the empty string rather than an exception, because a
        message is never the thing a decision should hinge on.
        """
        if self.status is VerdictStatus.FAILURE:
            wrote = (
                f'"status": "{_StatusAlias.FAILED.value}" (read as success=false, #1324)'
                if self.via_status_alias
                else "success=false"
            )
            return (
                f"Phase '{phase_id}' REPORTED FAILURE. Its agent ended with "
                f'TASK_RESULT {wrote}: "{self.comments}". The phase is failed '
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


#: Weakest to strongest, so the index IS the strength. The order is the
#: decision and is argued in the module docstring; this tuple is the only place
#: it is written down.
_STRENGTH: Final[tuple[VerdictStatus, ...]] = (
    VerdictStatus.NOT_REPORTED,
    VerdictStatus.UNREADABLE,
    VerdictStatus.SUCCESS,
    VerdictStatus.FAILURE,
)


def _settle(earlier: AgentVerdict, later: AgentVerdict) -> AgentVerdict:
    """Which of two claims by one phase stands. See the module docstring.

    Stated once, here, because both readings fold through it: the reports
    inside one message, and each message into a whole stream. Being a max over
    a fixed precedence rather than a rule about sequence is what makes those
    two agree - the same reports settle the same way however they were split
    up, so a message boundary is never somewhere a verdict can hide.

    Ties go to ``later`` only so that an agent restating the same claim is
    quoted in its own final words; no decision turns on it.
    """
    if _STRENGTH.index(later.status) >= _STRENGTH.index(earlier.status):
        return later
    return earlier


@dataclass(frozen=True)
class _Report:
    """The text of one report, and the JSON value that text carried.

    ``decoded`` is None when the message held a marker but no complete block
    under it - the payload is then the text an operator needs to see to work
    out what the agent wrote instead.

    ``repeats_status`` is the one question the decoded value can no longer be
    asked. A JSON decoder keeps only the last of duplicate members, so it
    travels from `_decode_payload` rather than being re-derived from `decoded`,
    where the evidence for it no longer exists.
    """

    payload: str
    decoded: object | None
    repeats_status: bool = False


class _ReportedResult(BaseModel):
    """The ``TASK_RESULT`` block, as a type instead of two string lookups.

    This replaces `decoded.get("success")` / `decoded.get("comments")`. Those
    read a parsed-but-unvalidated `object` by string key, so the keys were
    spelled in one place and their types checked in another, and every caller
    had to re-derive that a report is a mapping at all.

    ``strict`` is the point of the model, not a default carried along. The
    report crosses a trust boundary - an agent writes it - and pydantic's
    permissive mode would coerce ``"success": "true"`` into `True`. That is the
    exact direction this module exists to close: a string is not a JSON
    boolean, and a report that sends one has not reported an outcome. Under
    ``strict`` it fails validation and the verdict is UNREADABLE, which refuses
    the phase; under lax coercion it would silently PASS one. The old
    `isinstance(claim, bool)` check made the same judgement and this keeps it.

    ``extra="ignore"`` because agents add keys, and an unexpected one is not a
    reason to discard an otherwise well-formed outcome.
    """

    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    success: bool
    comments: object | None = None

    @property
    def said(self) -> str:
        """The comments as an operator will read them, never None."""
        return str(self.comments) if self.comments is not None else ""


class _StatusAlias(StrEnum):
    """The only two ``status`` spellings that name an outcome (#1324).

    The accepted spellings are written here and nowhere else. A closed set in
    one place is what separates an alias from a habit of adding one more string
    each time a run is lost, and it is the definition the negative tests are
    written against: everything not a member of this enum is UNREADABLE.
    """

    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def verdict(self) -> VerdictStatus:
        """The outcome this spelling names. Total over the members by shape."""
        return VerdictStatus.SUCCESS if self is _StatusAlias.COMPLETED else VerdictStatus.FAILURE


class _StatusAliasResult(BaseModel):
    """A block that named its outcome ``status``, and only in the exact shape.

    `_ReportedResult` is the contract; this is the single documented deviation
    from it that agents actually write, and the module docstring argues why
    reading it is not the coercion the strict model refuses. Everything the
    strict model buys is kept: ``status`` must be a JSON string (a bare `true`
    or `1` is not one), it must match a `_StatusAlias` value whole and
    case-sensitively, and both outcomes are carried so the alias refuses a
    phase as readily as it passes one.

    ``extra="ignore"`` for the same reason as the contract model: the observed
    blocks carry ``branch``, ``commit`` and ``pr`` beside the outcome, and an
    unexpected key is not a reason to discard a claim that is otherwise exact.
    """

    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    #: Per-field ``strict=False``, and nowhere else in this module. Strict
    #: validation of an enum demands an instance of it, which no JSON document
    #: can hold; lax validation of a `StrEnum` is an exact match against its
    #: values and coerces nothing - ``"Completed"``, ``"done"``, `True` and `1`
    #: are all refused, each pinned by a test.
    status: _StatusAlias = Field(strict=False)
    comments: object | None = None

    @model_validator(mode="before")
    @classmethod
    def _refuse_a_block_that_also_wrote_success(cls, block: object) -> object:
        """A block carrying BOTH keys is unreadable, never an alias.

        Without this, ``extra="ignore"`` would drop a ``success`` the agent DID
        write - a MALFORMED one, by the time a block reaches here, since
        `AgentVerdict._from_report` has already settled every readable boolean
        - and read the phase off its ``status`` instead. That undoes the strict
        refusal one line later and completes a phase on a report the contract
        just called unreadable, so the alias reads only a block that has
        nothing for it to disagree with.

        Kept as a rule of this model and not left to the ordering in
        `_from_report`, even though that ordering already means no readable
        ``success`` reaches here. The ordering decides which reading WINS; this
        decides what the alias is willing to read at all, and the alias has to
        be safe on its own terms whatever is handed to it.
        """
        if isinstance(block, dict) and "success" in block:
            raise ValueError("a block that wrote 'success' is judged by the contract, not aliased")
        return block

    @property
    def said(self) -> str:
        """The agent's comments, or - when it wrote none - the drift itself.

        An aliased block with nothing to quote would otherwise reach an
        operator as an empty string, which reads as "the agent said nothing"
        rather than "the agent did not report the way it was asked to".
        """
        if self.comments is not None:
            return str(self.comments)
        return (
            f'No comments were written. The phase reported "status": "{self.status.value}" '
            f'instead of a "success" boolean and was read as '
            f"{self.status.verdict.name} on that (#1324)."
        )


#: The key the alias reads, and the field `_StatusAliasResult` declares. It is
#: spelled here as well because a duplicate member is a property of the TEXT:
#: the model is handed a value that has already lost every duplicate but one, so
#: it is not something the model can be made to notice.
_ALIAS_KEY: Final[str] = "status"


@dataclass(frozen=True)
class _DecodedPayload:
    """One JSON value read out of a message, and what reading it cost."""

    value: object
    ends_at: int
    repeats_status: bool


def _decode_payload(text: str, at: int) -> _DecodedPayload:
    """The JSON value beginning at ``at``, and whether it named ``status`` twice.

    DUPLICATE MEMBERS ARE READ HERE OR NOWHERE. ``{"status": "failed",
    "status": "completed"}`` is legal JSON and a decoder keeps the last of the
    two, so what comes out is an ordinary, exact, unambiguous success and the
    failure the agent wrote has been deleted by the parser. No later check can
    recover it: the member list is the only place it still exists, and this is
    the only point at which anything here holds one. That is why the answer is
    carried out on the `_Report` instead of being asked of the value.

    ONLY THE OUTERMOST OBJECT IS ASKED, because a repeated key under
    ``comments`` or ``detail`` is a malformed note and not a block naming its
    own outcome twice. That falls out of the hook rather than being tested
    for: it runs on every object in the value, and an object cannot be
    finished before its members are, so the outermost one is always the LAST
    call and the answer left standing is its own. Accumulating across the
    calls - ``repeated = repeated or ...`` - is the way to get this wrong, and
    it would refuse a block whose top-level outcome is perfectly exact.

    Raises `ValueError` when no complete JSON value begins at ``at``, exactly
    as `json.JSONDecoder.raw_decode` does.
    """
    repeated = False

    def keep_the_member_list(members: list[tuple[str, object]]) -> object:
        nonlocal repeated
        repeated = sum(1 for key, _ in members if key == _ALIAS_KEY) > 1
        return dict(members)

    value, ends_at = json.JSONDecoder(object_pairs_hook=keep_the_member_list).raw_decode(text, at)
    return _DecodedPayload(value, ends_at, repeats_status=repeated)


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
    reports: list[_Report] = []
    unclosed_at: int | None = None
    search_from = 0
    while (marker_at := text.find(TASK_RESULT_MARKER, search_from)) != -1:
        payload_at = _payload_starts(text, marker_at + len(TASK_RESULT_MARKER))
        opening = _OPENING_FENCE.match(text, payload_at)
        value_at = _payload_starts(text, opening.end()) if opening else payload_at
        try:
            block = _decode_payload(text, value_at)
        except ValueError:
            # No value here to delimit, so resume just past the marker rather
            # than skipping over text this never read.
            unclosed_at = payload_at
            search_from = payload_at
            continue
        terminator_at = _payload_starts(text, block.ends_at)
        if opening:
            # A fence is accepted only as a pair around the one value; without
            # its closing half the block is as unclosed as any other.
            if not text.startswith(_CODE_FENCE, terminator_at):
                unclosed_at = payload_at
                search_from = block.ends_at
                continue
            terminator_at = _payload_starts(text, terminator_at + len(_CODE_FENCE))
        if not _terminates_at(text, terminator_at):
            unclosed_at = payload_at
            search_from = block.ends_at
            continue
        if opening:
            logger.warning(
                "TASK_RESULT block was wrapped in a markdown code fence (%r); "
                "unwrapped it and read the JSON inside (#1324)",
                opening.group(0),
            )
        reports.append(
            _Report(
                payload=text[value_at : block.ends_at],
                decoded=block.value,
                repeats_status=block.repeats_status,
            )
        )
        search_from = block.ends_at + len(TASK_RESULT_TERMINATOR)
    if reports:
        return reports
    if unclosed_at is None:
        return []
    return [_Report(payload=text[unclosed_at:], decoded=None)]


def _terminates_at(text: str, at: int) -> bool:
    """Whether the terminator, and not merely something starting with it, is here.

    `startswith` alone accepted `TASK_RESULT_ENDoops` and `TASK_RESULT_ENDING`,
    closing the block on a token the agent never wrote. The grammar this module
    documents is a marker, one JSON value and `TASK_RESULT_END`; a longer word
    that happens to share that prefix is not the terminator, and treating it as
    one completes a phase on a report nobody can be said to have terminated.

    The boundary is end-of-input or a non-word character. Word characters are
    the only ones that could have been part of an identifier the writer meant,
    so anything else - whitespace, punctuation, a newline - genuinely ends it.
    """
    if not text.startswith(TASK_RESULT_TERMINATOR, at):
        return False
    after = at + len(TASK_RESULT_TERMINATOR)
    if after >= len(text):
        return True
    return not (text[after].isalnum() or text[after] == "_")


def _excerpt(raw: str) -> str:
    """The unreadable text, short enough to sit in an error message."""
    flattened = " ".join(raw.split())
    return flattened if len(flattened) <= 200 else f"{flattened[:200]}…"
