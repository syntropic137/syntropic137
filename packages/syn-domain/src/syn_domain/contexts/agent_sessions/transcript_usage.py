"""Token usage recovered from a STORED transcript (issue #895).

WHY THIS LIVES HERE rather than in agentic-primitives, given the boundary rule
in AGENTS.md: this parses a stored document identified by its ``source_format``
under APS-V1-0004, not a live CLI's interface. syn137 implements the receiving
end of that standard, and a store that cannot index its own content is not a
store. The contract is the recorded format, which is versioned and named, not
whatever the CLI is doing this week.

THE TWO HARNESSES ARE INVERTED, and this is the trap under all the others:

    claude-code-jsonl   per-message DELTAS  -> SUM them
    codex rollout       running TOTALS      -> take the LAST

Apply either rule to the other harness and you get a number nobody would
question. Verified on real transcripts: summing a codex rollout's running
totals overcounted by 2.5x on one session and 4.7x on another, and I reported
12,206 for a session whose true total is 49,654 by reading the FIRST running
total instead of the last.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

#: A codex rollout is a JSON array of records; a claude transcript is JSONL
#: text. Typed as the two real shapes rather than Any, so a caller passing the
#: wrong one is a type error rather than a zero.
type RolloutRecord = Mapping[str, object]
type RolloutDocument = list[RolloutRecord]
type StoredTranscript = RolloutDocument | str


class SourceFormat(StrEnum):
    """Stored transcript formats this can read.

    Values match the ``source_format`` a conforming store records, so an
    unrecognised one is a format we have not taught it rather than a guess.
    """

    CLAUDE_CODE_JSONL = "claude-code-jsonl"
    CODEX_ROLLOUT = "rollout"


@dataclass(frozen=True)
class TranscriptUsage:
    """Token usage for one stored session.

    ``has_usage`` is separate from the counts on purpose. A transcript that
    carries no usage and one that genuinely used zero tokens are different
    facts, and collapsing them reports an unparsed delegation as a free one.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    model: str | None = None
    message_count: int = 0
    has_usage: bool = False

    is_self_consistent: bool = True
    """Whether the numbers agree with each other.

    A stored format can MOVE under a fixed ``source_format`` string: a CLI
    upgrade can rename or restructure fields while the store still labels the
    document 'rollout'. When that happens a parser does not fail, it silently
    returns a plausible smaller number, which is the exact failure this work
    exists to remove.

    So the arithmetic is checked rather than assumed. Where a format states its
    own total, that total must equal the parts. A False here means the parse is
    not trustworthy and the caller must treat the session as unpriced rather
    than cheap.
    """

    @property
    def billable_input_tokens(self) -> int:
        """Input tokens excluding the cached portion.

        For codex, ``cached_input_tokens`` is a SUBSET of ``input_tokens``,
        verified arithmetically: input 49250 + output 404 == total 49654, with
        cached 45056 sitting inside the input figure. Adding them together
        double-counts, and the inflated number still looks plausible.
        """
        return max(self.input_tokens - self.cache_read_tokens, 0)


def _as_int(value: object) -> int:
    """Coerce a JSON number to int, treating anything else as absent.

    A stored transcript is external data. If a CLI upgrade turns a count into
    a string or null, this must read as zero rather than raise: the caller
    then sees an unpriceable session, which is recoverable, instead of an
    exception that loses the whole import.
    """
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _codex_model(record: RolloutRecord) -> str | None:
    """The model, which a rollout carries on turn_context rather than on usage."""
    if record.get("type") != "turn_context":
        return None
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return None
    model = payload.get("model")
    return model if isinstance(model, str) else None


def _codex_running_total(record: RolloutRecord) -> Mapping[str, object] | None:
    """This record's cumulative usage, if it carries one."""
    if record.get("type") != "event_msg":
        return None
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return None
    info = payload.get("info")
    if not isinstance(info, Mapping):
        return None
    usage = info.get("total_token_usage")
    return usage if isinstance(usage, Mapping) else None


def _codex_usage(document: RolloutDocument) -> TranscriptUsage:
    """Read the LAST running total from a codex rollout.

    ``total_token_usage`` is cumulative, so the final one IS the session total.
    Summing them across events multiplies the answer by roughly the turn count:
    123,496 against a true 49,654 on the recorded fixture.
    """
    model: str | None = None
    latest: Mapping[str, object] | None = None
    turns = 0

    for record in document:
        if not isinstance(record, Mapping):
            continue
        model = _codex_model(record) or model
        usage = _codex_running_total(record)
        if usage is not None:
            latest = usage
            turns += 1

    if latest is None:
        return TranscriptUsage(model=model)

    input_tokens = _as_int(latest.get("input_tokens"))
    output_tokens = _as_int(latest.get("output_tokens"))
    cached = _as_int(latest.get("cached_input_tokens"))
    stated_total = _as_int(latest.get("total_tokens"))
    # Read rather than ignore. A rollout does not carry this today, but codex
    # 0.150.1 adds cache_write_input_tokens on the stdout side, and an ignored
    # cache-write field is an UNDERCOUNT, which is the direction this work
    # keeps failing in. Reading it now costs nothing and fails safe if the
    # rollout gains it later.
    cache_write = _as_int(latest.get("cache_write_input_tokens"))

    # The rollout states its own total, so the parts must reconcile to it. If a
    # CLI upgrade moves this schema while the store still calls it 'rollout',
    # this is what notices, instead of us reporting a confidently wrong figure.
    consistent = (input_tokens + output_tokens) == stated_total and cached <= input_tokens

    return TranscriptUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_write,
        # A rollout's cached figure is the cached READ portion, and it is a
        # subset of input_tokens rather than an addition to it.
        cache_read_tokens=cached,
        total_tokens=stated_total,
        model=model,
        message_count=turns,
        has_usage=True,
        is_self_consistent=consistent,
    )


def _claude_usage(document: str) -> TranscriptUsage:
    """Sum per-message deltas from a claude-code JSONL transcript.

    Each assistant message carries its OWN usage, not a running total, so the
    session total is their sum. Taking the last would report only the final
    turn, which for a long delegation is a small fraction of the truth.
    """
    totals = {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0}
    model: str | None = None
    messages = 0

    for line in document.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            # A truncated final line is normal for a killed run. Skipping it
            # loses one message; raising would lose the whole session.
            continue
        message = record.get("message") if isinstance(record, dict) else None
        if not isinstance(message, dict):
            continue
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        candidate = message.get("model")
        model = candidate if isinstance(candidate, str) else model
        messages += 1
        totals["input"] += _as_int(usage.get("input_tokens"))
        totals["output"] += _as_int(usage.get("output_tokens"))
        totals["cache_creation"] += _as_int(usage.get("cache_creation_input_tokens"))
        totals["cache_read"] += _as_int(usage.get("cache_read_input_tokens"))

    if messages == 0:
        return TranscriptUsage(model=model)

    return TranscriptUsage(
        input_tokens=totals["input"],
        output_tokens=totals["output"],
        cache_creation_tokens=totals["cache_creation"],
        cache_read_tokens=totals["cache_read"],
        total_tokens=totals["input"] + totals["output"],
        model=model,
        message_count=messages,
        has_usage=True,
    )


def extract_usage(source_format: SourceFormat, document: StoredTranscript) -> TranscriptUsage:
    """Recover token usage from a stored transcript.

    Raises:
        ValueError: for a format this does not know. Deliberate: returning a
            zeroed result for an unrecognised format would report an unparsed
            delegation as a free one, which is the failure this work exists to
            remove rather than relocate.
    """
    if source_format == SourceFormat.CODEX_ROLLOUT and isinstance(document, list):
        return _codex_usage(document)
    if source_format == SourceFormat.CLAUDE_CODE_JSONL and isinstance(document, str):
        return _claude_usage(document)

    msg = f"unsupported source_format: {source_format!r}"
    raise ValueError(msg)
