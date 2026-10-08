"""What kind of upstream fault ended an attempt, shared by the contexts that meet it (#1592, #1593).

The kind is decided where the upstream is spoken to - a harness adapter for a
model provider, the GitHub client for GitHub - and what it MEANS (resume, or
fetch an operator) is the same everywhere it is read. Here, in the shared
kernel, so the GitHub adapter can raise it without importing orchestration and
orchestration can store it without importing the GitHub adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime  # noqa: TC003 - a dataclass field, read at runtime
from enum import StrEnum


class UpstreamFailureKind(StrEnum):
    """The upstream's own account of why it did not serve an attempt (#1592).

    In the shared kernel because two contexts speak it (#1593): the
    WorkflowFailed event stores it, and the GitHub adapter raises it. A context
    module here would make every GitHub adapter reach into orchestration.
    """

    CAPACITY = "capacity"
    """The model provider had no capacity for the request (overloaded, 529)."""

    RATE_LIMITED = "rate_limited"
    """The provider is throttling us (429)."""

    AUTH = "auth"
    """The provider refused our credentials or their permissions (401, 403)."""

    QUOTA = "quota"
    """The account's usage allowance is spent until a reset the provider names (PC-83).

    Distinct from `CAPACITY` because it asks the opposite of a retry: capacity
    returns in seconds, a quota returns on a calendar date, so no backoff a
    phase can afford ever clears it. Never transient, never retried; the only
    useful next step is a different agent (a phase's `fallback_agent`) or a
    wait for the reset.
    """

    UNAVAILABLE = "unavailable"
    """The service did not answer: a dropped connection, a timeout, a 502/503/504
    after every retry it was allowed (#1593)."""

    UNKNOWN = "unknown"
    """The harness reported a fault, and nothing recognised its kind."""

    @property
    def is_transient(self) -> bool:
        """Whether another attempt may succeed with nothing changed: the phase is resumable."""
        return self in (
            UpstreamFailureKind.CAPACITY,
            UpstreamFailureKind.RATE_LIMITED,
            UpstreamFailureKind.UNAVAILABLE,
        )

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
        if self is UpstreamFailureKind.QUOTA:
            return (
                f"Upstream failure: {self.value} - not retried; nothing clears it before "
                "the provider's reset except a different agent."
            )
        return f"Upstream failure: {self.value} - not recognised; read the reason above."


@dataclass(frozen=True)
class QuotaExhaustion:
    """Which provider's quota is spent, and when it says it comes back (PC-83).

    ``resets_at`` is None when the provider named no time, or named one that
    could not be read; the account then says so rather than guessing a date.
    """

    provider: str
    resets_at: datetime | None = None

    def account(self) -> str:
        """The sentence a failed phase leads with: ``<provider> quota exhausted until <time>``."""
        until = self.resets_at.isoformat() if self.resets_at is not None else "an unstated time"
        return f"{self.provider} quota exhausted until {until}"


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
