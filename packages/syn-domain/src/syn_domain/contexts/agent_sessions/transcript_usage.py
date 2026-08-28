"""Token usage recovered from a STORED transcript (issue #895).

WHY THIS LIVES HERE, given the boundary rule in AGENTS.md: this parses a
stored document identified by its ``source_format`` under APS-V1-0004, not a
live CLI's interface. syn137 implements the receiving end of that standard,
and a store that cannot index its own content is not a store.

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
from enum import StrEnum
from itertools import pairwise

type RolloutRecord = Mapping[str, object]
type RolloutDocument = Sequence[RolloutRecord]
type StoredTranscript = RolloutDocument | str


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


@dataclass(frozen=True)
class PricedUsage:
    """Usage in canonical buckets, safe to price.

    Every field is an INDEPENDENT bucket. Nothing here is a subset of anything
    else, whichever harness produced it, which is the whole point of
    normalising at parse time.
    """

    model: str | None
    uncached_input_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    output_tokens: int
    message_count: int

    @property
    def total_tokens(self) -> int:
        """Sum of the four buckets. Safe precisely because they are disjoint."""
        return (
            self.uncached_input_tokens
            + self.cache_read_tokens
            + self.cache_creation_tokens
            + self.output_tokens
        )


@dataclass(frozen=True)
class NoUsage:
    """The transcript carried no usage at all.

    Distinct from a session that used nothing. Collapsing the two reports an
    unparsed delegation as a free one.
    """


class RetryDisposition(StrEnum):
    """Whether re-reading could change an unpriced verdict.

    Three states rather than a boolean, because "the store does not have it"
    and "the store could not be reached" are both retryable but end for
    different reasons, and conflating either with a permanent failure is how
    this fails silently.
    """

    PERMANENT = "permanent"
    """Asking again cannot help. The transcript is present and unreadable, the
    format is unsupported, or the record contradicts itself."""

    MISSING = "missing"
    """The store does not have this session YET.

    Capture lands AFTER an execution reports completed, so a reader arriving
    promptly sees an empty store for sessions that appear seconds later. This
    Capture confirmed the session, so this means late rather than absent, and
    an explicit retry bound is what ends the wait.
    """

    TRANSIENT = "transient"
    """The store could not be reached or answered badly.

    Distinct from MISSING because no capture counter can retire it: a reset
    connection says nothing about how many sessions exist, so it must be
    retried on its own terms rather than resolved by counting.
    """


@dataclass(frozen=True)
class UnpricedUsage:
    """The parse cannot be trusted, so it exposes NO counters.

    Deliberately carries no token fields. An advisory flag beside plausible
    numbers is not enough: a caller reads the numbers. The only safe shape is
    one where there is nothing to read, so an untrustworthy parse becomes a
    visible gap rather than a confident undercount.
    """

    reason: str

    retry: RetryDisposition = RetryDisposition.PERMANENT
    """Whether asking again could ever produce a different answer.

    A TYPED discriminator rather than a caller matching on ``reason`` prose,
    because the cases need opposite handling and prose drifts without a test
    noticing. Defaulting to PERMANENT means a new unpriced branch has to opt
    IN to being retried, so the mistake a careless addition makes is a visible
    gap rather than an endless retry loop.
    """


type UsageResult = PricedUsage | NoUsage | UnpricedUsage


def _as_count(value: object) -> int | None:
    """A non-negative token count, or None if this is not one.

    Returns None rather than 0 for anything unexpected. Collapsing a moved or
    renamed field into zero is what makes a broken parse look cheap instead of
    broken.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _counts(source: Mapping[str, object], fields: Sequence[str]) -> list[int] | None:
    """Read every named count, or None if any is MISSING or malformed.

    A missing field is not a zero. Defaulting it to zero is what let an empty
    usage object read as a free delegation: every count came back 0, the
    arithmetic reconciled trivially, and the result looked priceable. Absence
    of a field we require means the shape is not what we think it is.
    """
    out: list[int] = []
    for name in fields:
        if name not in source:
            return None
        count = _as_count(source[name])
        if count is None:
            return None
        out.append(count)
    return out


_CODEX_FIELDS = ("input_tokens", "output_tokens", "cached_input_tokens", "total_tokens")
_CLAUDE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


#: Any of these appearing on an event's ``info`` means the record is in the
#: business of reporting tokens. If one is present and total_token_usage
#: cannot be read, the schema has moved and the record must be REFUSED rather
#: than skipped: skipping returns the preceding cumulative total as if it were
#: current, which reports a long session at an early turn's cost.
_USAGE_MARKERS = ("total_token_usage", "last_token_usage", "token_usage", "usage")


def _looks_like_usage(info: Mapping[str, object]) -> bool:
    return any(marker in info for marker in _USAGE_MARKERS)


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


def _optional_count(source: Mapping[str, object], name: str) -> int | None | _Unreadable:
    """A count that may legitimately be absent.

    Three outcomes, and collapsing any two of them is how a number goes wrong:
    absent (None, fine), readable (the value), or PRESENT AND MALFORMED
    (_Unreadable). ``_as_count(...) or 0`` collapsed the third into zero, which
    silently underprices, and cache_write is exactly the field the CLI bump
    just added.
    """
    if name not in source:
        return None
    count = _as_count(source[name])
    return _UNREADABLE if count is None else count


def _optional_counts(source: Mapping[str, object], names: Sequence[str]) -> list[int] | _Unreadable:
    """Read counts that may be absent, refusing any that are present but bad."""
    out: list[int] = []
    for name in names:
        read = _optional_count(source, name)
        if isinstance(read, _Unreadable):
            return _UNREADABLE
        out.append(read or 0)
    return out


def _delta_total(info: Mapping[str, object]) -> int | None | _Unreadable:
    """This turn's own total, for the independent sum(deltas) check."""
    delta = info.get("last_token_usage")
    if not isinstance(delta, Mapping):
        return None
    return _optional_count(delta, "total_tokens")


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
    if not _looks_like_usage(info):
        return None

    usage = info.get("total_token_usage")
    if not isinstance(usage, Mapping):
        return _UNREADABLE
    counts = _counts(usage, _CODEX_FIELDS)
    if counts is None:
        return _UNREADABLE

    optional = _optional_counts(usage, ("cache_write_input_tokens", "reasoning_output_tokens"))
    delta_total = _delta_total(info)
    if isinstance(optional, _Unreadable) or isinstance(delta_total, _Unreadable):
        return _UNREADABLE
    cache_write, reasoning = optional

    return _CodexSnapshot(
        input_tokens=counts[0],
        output_tokens=counts[1],
        cached_input_tokens=counts[2],
        reasoning_output_tokens=reasoning,
        total_tokens=counts[3],
        cache_write_tokens=cache_write,
        delta_total_tokens=delta_total,
    )


def _codex_model(record: RolloutRecord) -> str | None:
    """The model, which a rollout carries on turn_context rather than on usage."""
    if record.get("type") != "turn_context":
        return None
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return None
    model = payload.get("model")
    return model if isinstance(model, str) else None


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
        model = _codex_model(record)
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


def _claude_entry(record: object) -> tuple[list[int], str | None] | _Unreadable | None:
    """This line's usage counts and model, None if it carries none."""
    if not isinstance(record, Mapping):
        return None
    message = record.get("message")
    if not isinstance(message, Mapping):
        return None
    usage = message.get("usage")
    if not isinstance(usage, Mapping):
        return None
    counts = _counts(usage, _CLAUDE_FIELDS)
    if counts is None:
        return _UNREADABLE
    model = message.get("model")
    return counts, model if isinstance(model, str) else None


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

    for line in document.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            # A transcript is a record of what happened. A line we cannot read
            # may have carried usage, so the total is no longer knowable and
            # saying so beats reporting the rest as if it were complete.
            return UnpricedUsage("transcript contains an unreadable line")
        entry = _claude_entry(record)
        if isinstance(entry, _Unreadable):
            return UnpricedUsage("usage present but unreadable")
        if entry is None:
            continue
        counts, model = entry
        if model is not None:
            models.add(model)
        messages += 1
        totals = [running + delta for running, delta in zip(totals, counts, strict=True)]

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
