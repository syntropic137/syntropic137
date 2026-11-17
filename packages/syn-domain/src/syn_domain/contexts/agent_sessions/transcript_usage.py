"""What token usage recovered from a STORED transcript means (issues #895, #1424).

The domain half of the split. This module says what a usage result IS -
priced in canonical buckets, absent, or refused - and nothing about how any
harness spells its transcript. Reading a stored ``claude-code-jsonl`` or codex
rollout into one of these is an adapter's job, behind
``TranscriptUsageReader`` (``ports/TranscriptUsageReaderPort.py``); the
implementation is ``syn_adapters.session_store.transcript_usage``.

NO FORMAT READER REMAINS HERE. The codex rollout's model field is read in the
adapter as well (``syn_adapters.session_store.codex_rollout_model``), and
orchestration receives the model it names through ``CodexRolloutPort``.
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
