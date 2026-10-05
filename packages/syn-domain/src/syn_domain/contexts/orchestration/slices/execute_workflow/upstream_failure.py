"""What kind of upstream fault ended an agent attempt, and what it asks of us (#1592).

Two failures that both read as "the platform failed" demand OPPOSITE
responses. A provider with no capacity this second has told us nothing about
the request, and the same attempt a few seconds later is likely to succeed:
it is transient, and the phase is resumable. A provider that refused our
credentials will refuse them on every attempt until somebody fixes the login:
retrying only spends the phase's budget again, and the run needs an operator.

So the domain asks ONE question - "what kind of upstream fault was this?" -
through `UpstreamFailureReader`, and decides what each kind means here.
Recognising a kind from a harness's own words is harness knowledge, which
changes whenever a CLI does, and is not decided here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Protocol

from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    codex_fault_reason,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    ApiErrorType,
    api_error_label,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


class UpstreamFailureKind(StrEnum):
    """The upstream's own account of why it did not serve an attempt."""

    CAPACITY = "capacity"
    """The model provider had no capacity for the request (overloaded, 529)."""

    RATE_LIMITED = "rate_limited"
    """The provider is throttling us (429)."""

    AUTH = "auth"
    """The provider refused our credentials or their permissions (401, 403)."""

    UNKNOWN = "unknown"
    """The harness reported a fault, and nothing recognised its kind."""

    @property
    def is_transient(self) -> bool:
        """Whether another attempt may succeed with nothing changed: the phase is resumable."""
        return self in (UpstreamFailureKind.CAPACITY, UpstreamFailureKind.RATE_LIMITED)

    @property
    def needs_operator(self) -> bool:
        """Whether nothing will succeed until somebody fixes the platform's access."""
        return self is UpstreamFailureKind.AUTH

    def account(self) -> str:
        """The sentence an operator reads beside the failure, saying what to do about it."""
        if self.is_transient:
            return f"Upstream failure: {self.value} - transient; the phase is resumable."
        if self.needs_operator:
            return f"Upstream failure: {self.value} - an operator must fix the credentials."
        return f"Upstream failure: {self.value} - not recognised; read the reason above."


class UpstreamFailureReader(Protocol):
    """The port: what kind of upstream fault an attempt's normalised failure reason is."""

    def kind_of(self, reason: str | None) -> UpstreamFailureKind | None:
        """The kind, or None when the attempt reported no fault at all."""
        ...


#: The one sentence codex says about its own capacity, observed in #1303. Codex
#: does not promise to keep saying it; a new phrasing reads as `UNKNOWN`,
#: which is not retried - the safe direction to be wrong in.
_CODEX_AT_CAPACITY = "Selected model is at capacity. Please try a different model."


def _claude_spellings(
    kind: UpstreamFailureKind, faults: tuple[tuple[ApiErrorType, str], ...]
) -> Iterator[tuple[str, UpstreamFailureKind]]:
    """Every spelling the claude parser gives these faults, with and without the status."""
    for error_type, status in faults:
        yield api_error_label(error_type), kind
        yield api_error_label(error_type, status), kind


class StreamReasonUpstreamFailureReader:
    """The port, read from the stream processors' normalised `error_reason` text.

    TODO(#1605): harness text does not belong in syn-domain. This adapter
    exists only until agentic-workspace's harness adapters carry the kind on
    their normalised result; then it is replaced by one that reads that field.

    MEMBERSHIP IS BY EQUALITY, NEVER CONTAINMENT. `Rate limit reached; quota
    resets next month` CONTAINS "rate limit" and is permanent, and an agent
    that merely quotes one of these sentences must not forge the signal. Each
    spelling is asked of the function that produces it, so this table cannot
    disagree with the string a stream processor actually wrote.
    """

    _KINDS: ClassVar[dict[str, UpstreamFailureKind]] = {
        **dict(
            _claude_spellings(UpstreamFailureKind.CAPACITY, ((ApiErrorType.OVERLOADED, "529"),))
        ),
        **dict(
            _claude_spellings(UpstreamFailureKind.RATE_LIMITED, ((ApiErrorType.RATE_LIMIT, "429"),))
        ),
        **dict(
            _claude_spellings(
                UpstreamFailureKind.AUTH,
                ((ApiErrorType.AUTHENTICATION, "401"), (ApiErrorType.PERMISSION, "403")),
            )
        ),
        codex_fault_reason(_CODEX_AT_CAPACITY): UpstreamFailureKind.CAPACITY,
    }

    def kind_of(self, reason: str | None) -> UpstreamFailureKind | None:
        if reason is None:
            return None
        return self._KINDS.get(reason, UpstreamFailureKind.UNKNOWN)


#: The reader production uses. Replace this, not its callers, for #1605.
UPSTREAM_FAILURES: UpstreamFailureReader = StreamReasonUpstreamFailureReader()
