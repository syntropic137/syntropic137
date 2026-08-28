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

    Values match the ``source_format`` a conforming store records, so an
    unrecognised one is a format we have not taught it rather than a guess.
    """

    CLAUDE_CODE_JSONL = "claude-code-jsonl"
    CODEX_ROLLOUT = "rollout"


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


@dataclass(frozen=True)
class UnpricedUsage:
    """The parse cannot be trusted, so it exposes NO counters.

    Deliberately carries no token fields. An advisory flag beside plausible
    numbers is not enough: a caller reads the numbers. The only safe shape is
    one where there is nothing to read, so an untrustworthy parse becomes a
    visible gap rather than a confident undercount.
    """

    reason: str


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


@dataclass(frozen=True)
class _CodexSnapshot:
    """One cumulative reading from a rollout."""

    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    total_tokens: int
    cache_write_tokens: int


def _codex_snapshot(record: RolloutRecord) -> _CodexSnapshot | None:
    if record.get("type") != "event_msg":
        return None
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return None
    info = payload.get("info")
    if not isinstance(info, Mapping):
        return None
    usage = info.get("total_token_usage")
    if not isinstance(usage, Mapping):
        return None
    counts = _counts(usage, _CODEX_FIELDS)
    if counts is None:
        return None
    # Absent today. Read anyway: codex 0.150.1 adds it on the stdout side, and
    # an ignored cache-write field is an UNDERCOUNT.
    cache_write = _as_count(usage.get("cache_write_input_tokens", 0)) or 0
    return _CodexSnapshot(counts[0], counts[1], counts[2], counts[3], cache_write)


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

    # Cumulative readings only ever grow. A decrease means these are not
    # cumulative, and last-wins would then be the wrong rule entirely.
    for earlier, later in pairwise(snapshots):
        if (
            later.input_tokens < earlier.input_tokens
            or later.output_tokens < earlier.output_tokens
            or later.total_tokens < earlier.total_tokens
        ):
            return "cumulative totals decreased"

    return None


def _codex_usage_shaped(record: RolloutRecord) -> bool:
    """Whether this record LOOKS like it carries usage.

    Used to tell "no usage here" from "usage we could not read". Only the
    second is a moved schema, and only the second must refuse to price.
    """
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return False
    info = payload.get("info")
    return isinstance(info, Mapping) and "total_token_usage" in info


@dataclass(frozen=True)
class _CodexScan:
    """What one pass over a rollout found."""

    model: str | None
    snapshots: list[_CodexSnapshot]
    saw_unreadable: bool


def _scan_codex(document: RolloutDocument) -> _CodexScan:
    model: str | None = None
    snapshots: list[_CodexSnapshot] = []
    saw_unreadable = False

    for record in document:
        if not isinstance(record, Mapping):
            continue
        model = _codex_model(record) or model
        if record.get("type") != "event_msg":
            continue
        snapshot = _codex_snapshot(record)
        if snapshot is not None:
            snapshots.append(snapshot)
        elif _codex_usage_shaped(record):
            saw_unreadable = True

    return _CodexScan(model, snapshots, saw_unreadable)


def _codex_usage(document: RolloutDocument) -> UsageResult:
    """Take the LAST cumulative reading from a codex rollout, having checked it.

    Summing the readings multiplies the answer by roughly the turn count:
    123,496 against a true 49,654 on the recorded fixture.
    """
    scan = _scan_codex(document)

    if scan.saw_unreadable:
        # Shaped like usage but unreadable: a moved schema, not an absence.
        # Refusing is the difference between "unpriced" and "free".
        return UnpricedUsage("total_token_usage present but unreadable")
    if not scan.snapshots:
        return NoUsage()

    broken = _codex_invariant_broken(scan.snapshots)
    if broken is not None:
        return UnpricedUsage(broken)

    final = scan.snapshots[-1]
    return PricedUsage(
        model=scan.model,
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


def extract_usage(source_format: SourceFormat, document: StoredTranscript) -> UsageResult:
    """Recover token usage from a stored transcript.

    Raises:
        ValueError: for a format this does not know. Deliberate: a zeroed
            result would report an unparsed delegation as a free one.
    """
    if source_format == SourceFormat.CODEX_ROLLOUT and not isinstance(document, str):
        return _codex_usage(document)
    if source_format == SourceFormat.CLAUDE_CODE_JSONL and isinstance(document, str):
        return _claude_usage(document)

    msg = f"unsupported source_format: {source_format!r}"
    raise ValueError(msg)
