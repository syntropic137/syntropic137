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

from typing import TYPE_CHECKING, ClassVar, Protocol

__all__ = [
    "UPSTREAM_FAILURES",
    "StreamReasonUpstreamFailureReader",
    "UpstreamFailureError",
    "UpstreamFailureKind",
    "UpstreamFailureReader",
]

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    UpstreamFailureKind,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    codex_fault_reason,
    codex_login_fault_reason,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    ApiErrorType,
    api_error_label,
    api_error_with_message,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


class UpstreamFailureError(Exception):
    """A failure an upstream service reported, carrying its kind (#1593).

    The port for every upstream that is not an agent harness - GitHub during
    provisioning first. The adapter that talks to the service knows which kind
    its failure was and raises a subclass saying so; `failure_account` reads
    the kind off the exception and never off its message, so the domain
    learns what the failure asks of an operator without learning the service.
    """

    def __init__(self, message: str, *, upstream_kind: UpstreamFailureKind) -> None:
        super().__init__(message)
        self.upstream_kind = upstream_kind


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

    #: Auth faults the parsers report WITH detail appended: a codex login fault
    #: carries the CLI's log line, a claude error body its own message. Each
    #: prefix is what its producer writes with empty detail, and it is matched
    #: only at the start of the reason. Only `AUTH` is matched this way: it is
    #: never retried, so text that forges a prefix can at worst stop a retry
    #: `UNKNOWN` would not have made either - never cause one.
    _AUTH_PREFIXES: ClassVar[tuple[str, ...]] = (
        *(codex_login_fault_reason(status, "") for status in ("401", "403", "")),
        api_error_with_message(ApiErrorType.AUTHENTICATION, ""),
        api_error_with_message(ApiErrorType.PERMISSION, ""),
    )

    def kind_of(self, reason: str | None) -> UpstreamFailureKind | None:
        if reason is None:
            return None
        kind = self._KINDS.get(reason)
        if kind is not None:
            return kind
        if reason.startswith(self._AUTH_PREFIXES):
            return UpstreamFailureKind.AUTH
        return UpstreamFailureKind.UNKNOWN


#: The reader production uses. Replace this, not its callers, for #1605.
UPSTREAM_FAILURES: UpstreamFailureReader = StreamReasonUpstreamFailureReader()
