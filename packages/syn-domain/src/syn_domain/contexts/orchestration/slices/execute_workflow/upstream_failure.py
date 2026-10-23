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

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, assert_never

from agentic_isolation.harnesses import claude, codex
from agentic_isolation.harnesses.upstream_failure import UpstreamFailure
from agentic_isolation.harnesses.upstream_failure import (
    UpstreamFailureKind as HarnessFailureKind,
)

__all__ = [
    "UPSTREAM_FAILURES",
    "HarnessUpstreamFailureReader",
    "QuotaExhaustion",
    "UpstreamFailureError",
    "UpstreamFailureKind",
    "UpstreamFailureReader",
]

from syn_domain.contexts.orchestration.slices.execute_workflow.codex_faults import (
    codex_fault_reason,
)
from syn_shared.upstream_failure import QuotaExhaustion, UpstreamFailureError, UpstreamFailureKind

if TYPE_CHECKING:
    from collections.abc import Callable


class UpstreamFailureReader(Protocol):
    """The port: what kind of upstream fault an attempt's normalised failure reason is."""

    def kind_of(self, reason: str | None) -> UpstreamFailureKind | None:
        """The kind, or None when the attempt reported no fault at all."""
        ...

    def quota_of(self, reason: str | None) -> QuotaExhaustion | None:
        """Whose quota is spent and until when, or None when ``reason`` is not a quota fault.

        `kind_of` is `QUOTA` exactly when this is not None.
        """
        ...


#: What `CodexStreamProcessor` writes before codex's own words about a failed
#: turn. Its presence is how a reason is known to be codex's; every other
#: reason, a codex login fault included, is spelled the claude parser's way.
_CODEX_FAULT_LINE = codex_fault_reason("")


def _domain_kind(kind: HarnessFailureKind) -> UpstreamFailureKind:
    """The domain's kind for the harness's. Exhaustive: a new harness kind fails type-checking."""
    match kind:
        case HarnessFailureKind.CAPACITY:
            return UpstreamFailureKind.CAPACITY
        case HarnessFailureKind.RATE_LIMITED:
            return UpstreamFailureKind.RATE_LIMITED
        case HarnessFailureKind.QUOTA:
            return UpstreamFailureKind.QUOTA
        case HarnessFailureKind.AUTH:
            return UpstreamFailureKind.AUTH
        case HarnessFailureKind.REFUSAL:
            return UpstreamFailureKind.REFUSAL
        case HarnessFailureKind.UNKNOWN:
            return UpstreamFailureKind.UNKNOWN
        case _:
            assert_never(kind)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class HarnessUpstreamFailureReader:
    """The port, answered by agentic-workspace's harness classifiers (#1605).

    Recognising a harness's words is the harness's business: each harness
    package's ``classify_upstream_failure`` owns its strings, and this adapter
    only picks the harness and translates its answer into the domain's kind.

    The harness is picked by the fault line, never by searching the text: a
    reason is codex's only when it opens with `_CODEX_FAULT_LINE`, and codex
    is then asked about the words after it, so agent prose that quotes a
    codex sentence cannot forge a quota or a refusal - both of which buy a
    run on the fallback agent. Claude's classifier anchors its own matches.

    ``clock`` is when the reason is read. Claude names its reset without a
    year, and the classifier places it as the first such time after this; a
    reason is read moments after its run ended, so the year is the same one.
    """

    clock: Callable[[], datetime] = field(default=_now)

    def _classify(self, reason: str | None) -> tuple[str, UpstreamFailure | None]:
        """Which harness wrote ``reason``, and what its classifier makes of it."""
        observed_at = self.clock()
        if reason is not None and reason.startswith(_CODEX_FAULT_LINE):
            message = reason.removeprefix(_CODEX_FAULT_LINE)
            return "codex", codex.classify_upstream_failure(message, observed_at=observed_at)
        return "claude", claude.classify_upstream_failure(reason, observed_at=observed_at)

    def kind_of(self, reason: str | None) -> UpstreamFailureKind | None:
        _, failure = self._classify(reason)
        return _domain_kind(failure.kind) if failure is not None else None

    def quota_of(self, reason: str | None) -> QuotaExhaustion | None:
        provider, failure = self._classify(reason)
        if failure is None or failure.kind is not HarnessFailureKind.QUOTA:
            return None
        return QuotaExhaustion(provider=provider, resets_at=failure.resets_at)


#: The reader production uses: the one place the port is bound.
UPSTREAM_FAILURES: UpstreamFailureReader = HarnessUpstreamFailureReader()
