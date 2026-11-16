"""What token usage recovered from a STORED transcript means (issues #895, #1424).

The domain half of the split. This module says what a usage result IS -
priced in canonical buckets, absent, or refused - and nothing about how any
harness spells its transcript. Reading a stored ``claude-code-jsonl`` or codex
rollout into one of these is an adapter's job, behind
``TranscriptUsageReader`` (``ports/TranscriptUsageReaderPort.py``); the
implementation is ``syn_adapters.session_store.transcript_usage``.

ONE FORMAT READER REMAINS HERE: the codex rollout's ``turn_context`` model
field, read by ``rollout_record_model``. ``CodexStreamProcessor`` in
orchestration reads a codex phase's model through it (#1284), and the adapter
reuses the same reader so that field keeps exactly one reader in the system.
Moving it out needs ``CodexRolloutPort`` to return the model instead of the
records, which is part 2 of #1424.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

type RolloutRecord = Mapping[str, object]
type RolloutDocument = Sequence[RolloutRecord]
type StoredTranscript = RolloutDocument | str


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


def rollout_record_model(record: RolloutRecord) -> str | None:
    """The model one codex rollout record names, or None if it names none.

    A rollout carries its model on turn_context rather than on usage. This is
    the ONLY reader of that field: ``model_from_rollout`` below and the usage
    adapter's codex scan both go through it.
    """
    if record.get("type") != "turn_context":
        return None
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return None
    model = payload.get("model")
    return model if isinstance(model, str) else None


def model_from_rollout(document: RolloutDocument) -> str | None:
    """Which model a codex rollout says ran, or None if it does not say one.

    Codex names its model on disk and NOWHERE on its stdout stream, so this is
    the only place a codex phase's model can be observed at all (#1284). It is
    ``rollout_record_model``'s reader, not a second one: a rollout field with two
    readers drifts the moment codex moves it, and the failure is silent - both
    the price and the identity would go quietly unknown.

    None is returned for a rollout that names no model AND for one that names
    several. The second is the refusal the usage adapter already makes for
    pricing, for the same reason: a session that spanned models cannot be
    attributed to one of them, and naming whichever came first would read as
    evidence. The caller cannot tell those two apart, and does not need to -
    both mean "the rollout does not establish a model".

    A blank model names nothing and is dropped rather than returned. ``""``
    is not an id, and a caller that received one would carry it onward as
    though it were - which is the "unknown" sentinel mistake in a shorter
    spelling.
    """
    models = {
        model.strip()
        for record in document
        if isinstance(record, Mapping)
        and (model := rollout_record_model(record)) is not None
        and model.strip()
    }
    return next(iter(models)) if len(models) == 1 else None
