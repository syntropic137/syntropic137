"""Token usage recovered from a STORED transcript (issues #895, #1424).

The adapter behind ``TranscriptUsageReader``. It knows the stored formats a
conforming APS-V1-0004 store records (``claude-code-jsonl`` and
``codex-rollout-jsonl``) and how each one spells its usage. That is harness
knowledge, which changes when a CLI ships, so it lives here rather than in the
domain. What a usage result MEANS - ``PricedUsage``, ``NoUsage``,
``UnpricedUsage`` - stays in ``syn_domain.contexts.agent_sessions``.

THE HARNESSES DO NOT SHARE SEMANTICS, and a shared "billable input" property
cannot express both. That mistake priced a real Claude delegate at ZERO input
tokens, which is the silently-cheap failure this issue exists to remove,
reintroduced one layer up. So each parser normalises into the SAME canonical
buckets at parse time, and nothing downstream re-derives them:

    codex rollout      input_tokens INCLUDES cached_input_tokens
                       -> uncached = input - cached
    claude-code-jsonl  input_tokens EXCLUDES cache reads; independent buckets
                       -> uncached = input

The proof that they differ, from a real stored Claude delegate:
``input_tokens=7`` while ``cache_read_input_tokens=28340``. Under codex
semantics cached is a subset of input, so cached can never exceed it. Here it
is four thousand times larger. Subtracting is not imprecise, it is
definitionally wrong.

The two also differ in how usage accumulates:

    claude   per-message DELTAS   -> SUM them
    codex    running TOTALS       -> take the LAST

Verified by reading the FIRST running total out of a real rollout and getting
12,206 for a session whose true total is 49,654.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum, auto
from itertools import pairwise

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    ValidationError,
    field_validator,
)

from syn_adapters.session_store.codex_rollout_model import rollout_record_model
from syn_domain.contexts.agent_sessions.transcript_usage import (
    NoUsage,
    PricedUsage,
    RolloutDocument,
    RolloutRecord,
    StoredTranscript,
    UnpricedUsage,
    UsageResult,
)


class SourceFormat(StrEnum):
    """Stored transcript formats this can read.

    THESE LITERALS ARE THE STORE'S, NOT OURS. They must equal the
    ``source_format`` a conforming store actually records, and the only way to
    know that is to read a real record. Naming the codex one after the format's
    informal name gave ``"rollout"``, which matched nothing: every real codex
    transcript reports ``"codex-rollout-jsonl"``. A test pins both against
    metadata captured from live records so drift in either direction fails.
    """

    CLAUDE_CODE_JSONL = "claude-code-jsonl"
    CODEX_ROLLOUT = "codex-rollout-jsonl"


class _UsageCounts(BaseModel):
    """A usage object's counts, refined once where the transcript is read.

    STRICT, and every count a non-negative int. A bool, a float, a string or a
    negative number is not a count, and a REQUIRED count that is missing is not
    a zero: defaulting it to zero is what let an empty usage object read as a
    free delegation. Any of those fails validation, and the callers turn that
    failure into a refusal, never into a smaller number.

    Extra fields are ignored rather than forbidden: these are the harness's
    records, not ours, and a CLI adding a field must not unprice a session.
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")


class _CodexTotalUsage(_UsageCounts):
    """``total_token_usage`` on a codex ``event_msg``: running totals."""

    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    cached_input_tokens: NonNegativeInt
    total_tokens: NonNegativeInt
    cache_write_input_tokens: NonNegativeInt = 0
    """May be absent (the CLI bump that added it is recent). Absent is 0;
    present and malformed fails, rather than collapsing into a silent 0."""
    reasoning_output_tokens: NonNegativeInt = 0


class _CodexTurnUsage(_UsageCounts):
    """``last_token_usage``: this turn's own total, when it carries one.

    A present-but-null ``total_tokens`` fails like any other malformed count:
    the field is ``NonNegativeInt``, and the ``None`` default is only ever the
    ABSENT case, because Pydantic does not validate defaults.
    """

    total_tokens: NonNegativeInt | None = Field(default=None, validate_default=False)

    @field_validator("total_tokens", mode="before")
    @classmethod
    def _null_is_not_absent(cls, value: object) -> object:
        if value is None:
            raise ValueError("total_tokens is present and null")
        return value


class _ClaudeUsage(_UsageCounts):
    """``message.usage`` on a claude-code line: per-message deltas."""

    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    cache_creation_input_tokens: NonNegativeInt
    cache_read_input_tokens: NonNegativeInt


#: Any of these appearing on an event's ``info`` means the record is in the
#: business of reporting tokens. If one is present and total_token_usage
#: cannot be read, the schema has moved and the record must be REFUSED rather
#: than skipped: skipping returns the preceding cumulative total as if it were
#: current, which reports a long session at an early turn's cost.
_USAGE_MARKERS = ("total_token_usage", "last_token_usage", "token_usage", "usage")


@dataclass(frozen=True)
class _CodexSnapshot:
    """One cumulative reading from a rollout, with its per-turn delta."""

    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    cache_write_tokens: int
    delta_total_tokens: int | None
    """This turn's own total from last_token_usage, if it carried one.

    Parsed so the independent invariant sum(deltas) == final cumulative total
    can actually be checked. Without it, "cumulative" was an assumption rather
    than something verified.
    """


def _codex_snapshot(record: RolloutRecord) -> _CodexSnapshot | None | _Unreadable:
    """This record's cumulative reading.

    Returns _UNREADABLE when the record LOOKS like it carries usage but cannot
    be read, so a restructured record is refused rather than skipped. Skipping
    it silently returns the PRECEDING total as if it were current, which is the
    stale-value failure with a new trigger.
    """
    if record.get("type") != "event_msg":
        return None
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return None
    info = payload.get("info")
    if not isinstance(info, Mapping):
        return None
    if not any(marker in info for marker in _USAGE_MARKERS):
        return None

    usage = info.get("total_token_usage")
    delta = info.get("last_token_usage")
    try:
        total = _CodexTotalUsage.model_validate(usage)
        turn = _CodexTurnUsage.model_validate(delta) if isinstance(delta, Mapping) else None
    except ValidationError:
        return _UNREADABLE

    return _CodexSnapshot(
        input_tokens=total.input_tokens,
        output_tokens=total.output_tokens,
        cached_input_tokens=total.cached_input_tokens,
        reasoning_output_tokens=total.reasoning_output_tokens,
        total_tokens=total.total_tokens,
        cache_write_tokens=total.cache_write_input_tokens,
        delta_total_tokens=None if turn is None else turn.total_tokens,
    )


def _codex_invariant_broken(snapshots: Sequence[_CodexSnapshot]) -> str | None:
    """Why this rollout cannot be trusted, or None if it holds together.

    Each check names an assumption the pricing rests on. If one stops holding,
    the schema has moved under a fixed source_format, and the danger is not a
    crash: it is a smaller plausible number that reads as a cheap delegation.
    """
    final = snapshots[-1]

    # The rollout states its own total, so the parts must reconcile to it.
    if final.input_tokens + final.output_tokens != final.total_tokens:
        return "stated total does not equal its parts"

    # cached is a SUBSET of input, which is what makes uncached = input - cached
    # correct. Claude's buckets are independent and that subtraction would be
    # definitionally wrong there, so this is the check keeping them apart.
    if final.cached_input_tokens > final.input_tokens:
        return "cached input exceeds input"

    # Cumulative readings only ever grow, in EVERY component. Checking only
    # input/output/total let a cached-only decrease through, and cached is the
    # component the codex subtraction depends on.
    for earlier, later in pairwise(snapshots):
        if any(
            getattr(later, field) < getattr(earlier, field)
            for field in (
                "input_tokens",
                "output_tokens",
                "cached_input_tokens",
                "reasoning_output_tokens",
                "cache_write_tokens",
                "total_tokens",
            )
        ):
            return "cumulative totals decreased"

    # INDEPENDENT CHECK: per-turn deltas must sum to the final cumulative
    # total. This is the one invariant not derivable from the cumulative
    # figures themselves, so it is the only thing that can catch a cumulative
    # series that is internally tidy but wrong.
    deltas = [s.delta_total_tokens for s in snapshots]
    if all(delta is not None for delta in deltas):
        summed = sum(delta for delta in deltas if delta is not None)
        if summed != final.total_tokens:
            return f"per-turn deltas sum to {summed}, final total says {final.total_tokens}"

    # reasoning is a SUBSET of output, as cached is of input.
    if final.reasoning_output_tokens > final.output_tokens:
        return "reasoning output exceeds output"

    return None


@dataclass(frozen=True)
class _CodexScan:
    """What one pass over a rollout found."""

    models: set[str]
    snapshots: list[_CodexSnapshot]
    saw_unreadable: bool


def _scan_codex(document: RolloutDocument) -> _CodexScan:
    models: set[str] = set()
    snapshots: list[_CodexSnapshot] = []
    saw_unreadable = False

    for record in document:
        if not isinstance(record, Mapping):
            continue
        model = rollout_record_model(record)
        if model is not None:
            models.add(model)
        snapshot = _codex_snapshot(record)
        if isinstance(snapshot, _Unreadable):
            saw_unreadable = True
        elif snapshot is not None:
            snapshots.append(snapshot)

    return _CodexScan(models, snapshots, saw_unreadable)


def _codex_usage(document: RolloutDocument) -> UsageResult:
    """Take the LAST cumulative reading from a codex rollout, having checked it.

    Summing the readings multiplies the answer by roughly the turn count:
    123,496 against a true 49,654 on the recorded fixture.
    """
    scan = _scan_codex(document)

    if scan.saw_unreadable:
        # Shaped like usage but unreadable: a moved schema, not an absence.
        # Refusing is the difference between "unpriced" and "free".
        return UnpricedUsage("usage-bearing record present but unreadable")
    if not scan.snapshots:
        return NoUsage()
    if len(scan.models) > 1:
        # Matches the claude path. The two harnesses previously disagreed on
        # the same hazard: claude refused a mixed-model transcript while codex
        # billed the whole session at whichever model came last.
        return UnpricedUsage(f"transcript spans multiple models: {sorted(scan.models)}")

    broken = _codex_invariant_broken(scan.snapshots)
    if broken is not None:
        return UnpricedUsage(broken)

    final = scan.snapshots[-1]
    return PricedUsage(
        model=next(iter(scan.models), None),
        # input INCLUDES cached, so the uncached remainder is the billable part.
        uncached_input_tokens=final.input_tokens - final.cached_input_tokens,
        cache_read_tokens=final.cached_input_tokens,
        cache_creation_tokens=final.cache_write_tokens,
        output_tokens=final.output_tokens,
        message_count=len(scan.snapshots),
    )


@dataclass(frozen=True)
class _Unreadable:
    """Distinguishes "this line carries no usage" from "this line carries
    usage we cannot read". The first is normal; the second means the total is
    no longer knowable, so it must not be summed as if it were complete.

    A distinct type rather than a bare object() so the type checker can narrow
    it, and so a caller cannot accidentally treat it as data.
    """


_UNREADABLE = _Unreadable()


def _claude_entry(
    record: object,
) -> tuple[list[int], str | None, str | None] | _Unreadable | None:
    """This line's usage counts, model and message id; None if it carries none."""
    if not isinstance(record, Mapping):
        return None
    message = record.get("message")
    if not isinstance(message, Mapping):
        return None
    usage = message.get("usage")
    if not isinstance(usage, Mapping):
        return None
    try:
        read = _ClaudeUsage.model_validate(usage)
    except ValidationError:
        return _UNREADABLE
    counts = [
        read.input_tokens,
        read.output_tokens,
        read.cache_creation_input_tokens,
        read.cache_read_input_tokens,
    ]
    model = message.get("model")
    message_id = message.get("id")
    return (
        counts,
        model if isinstance(model, str) else None,
        message_id if isinstance(message_id, str) and message_id.strip() else None,
    )


class _Repeat(Enum):
    """What a message id says about a line that carries usage."""

    NEW = auto()

    ALREADY_COUNTED = auto()
    """The same response's next CONTENT BLOCK. Claude emits one assistant
    record per block, each repeating that response's identical usage, so
    summing them multiplies a turn by its block count. The live stream
    processor has deduplicated this way since #695."""

    CONTRADICTS = auto()
    """Same id, DIFFERENT numbers."""


def _repeat_verdict(
    seen: dict[str, tuple[list[int], str | None]],
    message_id: str | None,
    counts: list[int],
    model: str | None,
) -> _Repeat:
    """Classify this line against the ids already counted.

    A line with NO id is always NEW: nothing identifies it as a repeat, so
    dropping it would undercount a real turn.
    """
    if message_id is None:
        return _Repeat.NEW
    previous = seen.get(message_id)
    if previous is None:
        seen[message_id] = (counts, model)
        return _Repeat.NEW
    return _Repeat.ALREADY_COUNTED if previous == (counts, model) else _Repeat.CONTRADICTS


def _claude_lines(document: str) -> list[object] | UnpricedUsage:
    """Every non-blank line parsed, or a refusal if any is unreadable.

    A transcript is a record of what happened. A line we cannot read may have
    carried usage, so the total is no longer knowable, and saying so beats
    reporting the rest as if it were complete.
    """
    records: list[object] = []
    for line in document.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            records.append(json.loads(stripped))
        except (json.JSONDecodeError, ValueError):
            return UnpricedUsage("transcript contains an unreadable line")
    return records


def _claude_usage(document: str) -> UsageResult:
    """Sum per-message deltas from a claude-code JSONL transcript.

    Claude's ``input_tokens`` EXCLUDES cache reads; the buckets are
    independent. Subtracting a cache read from it, as codex requires, drives a
    real transcript to zero input: one measured delegate reported input 7
    against cache_read 28,340.
    """
    totals = [0, 0, 0, 0]
    models: set[str] = set()
    messages = 0
    seen: dict[str, tuple[list[int], str | None]] = {}

    records = _claude_lines(document)
    if isinstance(records, UnpricedUsage):
        return records

    for record in records:
        entry = _claude_entry(record)
        if isinstance(entry, _Unreadable):
            return UnpricedUsage("usage present but unreadable")
        if entry is None:
            continue
        counts, model, message_id = entry
        repeat = _repeat_verdict(seen, message_id, counts, model)
        if repeat is _Repeat.CONTRADICTS:
            # The transcript contradicts itself. First-wins would hide that,
            # and a quietly wrong total is worse than a visible refusal.
            return UnpricedUsage(f"message {message_id} appears twice with different usage")
        if repeat is _Repeat.ALREADY_COUNTED:
            continue
        if model is not None:
            models.add(model)
        messages += 1
        totals = [running + delta for running, delta in zip(totals, counts, strict=True)]

    return _claude_result(totals, models, messages)


def _claude_result(totals: list[int], models: set[str], messages: int) -> UsageResult:
    """Turn the accumulated scan into a result.

    Separate from the scan so the two failure shapes - nothing to price, and
    more than one model - are stated once, where they can be read together.
    """
    if messages == 0:
        return NoUsage()
    if len(models) > 1:
        # Tokens aggregate but a model does not. Billing a mixed transcript at
        # whichever model happened to be last is a silent mispricing, and
        # delegates can switch model mid-session.
        return UnpricedUsage(f"transcript spans multiple models: {sorted(models)}")

    return PricedUsage(
        model=next(iter(models), None),
        # Independent bucket. NOT reduced by cache reads.
        uncached_input_tokens=totals[0],
        cache_read_tokens=totals[3],
        cache_creation_tokens=totals[2],
        output_tokens=totals[1],
        message_count=messages,
    )


def _as_rollout(document: StoredTranscript) -> RolloutDocument | None:
    """A rollout, whether it arrived parsed or as the JSON text of one.

    WHY BOTH: the store serves a rollout from ``GET /v1/sessions/<id>/raw`` as
    ``application/json``, so a caller reading ``response.json()`` gets a list
    while one reading ``response.text`` gets a string. Accepting only the list
    meant the obvious caller priced every Claude session correctly and marked
    every CODEX session unpriced, with no exception and no failing test: half
    the delegate cost quietly missing, which is this bug one layer out.

    Parsing here removes the footgun rather than documenting it.
    """
    if not isinstance(document, str):
        return document
    try:
        parsed = json.loads(document)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, list) else None


def extract_usage(source_format: str, document: StoredTranscript) -> UsageResult:
    """Recover token usage from a stored transcript.

    Takes ``source_format`` as a plain ``str`` because that is what it IS: a
    value arriving from external data, not a choice this code makes.

    An unrecognised format returns ``UnpricedUsage`` rather than raising. It
    used to raise, which contradicted the principle the rest of this module
    implements: a malformed transcript already degrades one session to
    unpriced rather than failing, and an unknown format should degrade the
    same way. Raising turns one unrecognised session into a failed import of
    every session beside it, so a new harness, or one literal drifting as
    ``codex-rollout-jsonl`` did, becomes an outage instead of a gap.
    """
    if source_format == SourceFormat.CODEX_ROLLOUT:
        rollout = _as_rollout(document)
        if rollout is None:
            return UnpricedUsage("codex transcript is neither a record list nor JSON text")
        return _codex_usage(rollout)

    if source_format == SourceFormat.CLAUDE_CODE_JSONL:
        if not isinstance(document, str):
            # Names the actual mismatch. An earlier version reported this as an
            # unsupported format and listed that same format as known, in one
            # sentence, sending the reader after the wrong thing entirely.
            return UnpricedUsage(
                f"{source_format!r} expects JSONL text, got {type(document).__name__}"
            )
        return _claude_usage(document)

    known = sorted(fmt.value for fmt in SourceFormat)
    return UnpricedUsage(f"unsupported source_format {source_format!r}; known: {known}")


class StoredTranscriptUsageReader:
    """``TranscriptUsageReader`` over the formats a conforming store records."""

    def read_usage(self, source_format: str, document: StoredTranscript) -> UsageResult:
        return extract_usage(source_format, document)
