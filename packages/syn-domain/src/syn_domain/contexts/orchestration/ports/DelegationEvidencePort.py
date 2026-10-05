"""Port for reading which delegates a phase's workspace launched, and how they ended (#894).

WHY THIS IS A PORT. A declared delegation is checked against the record the
delegate itself wrote - the workspace's child journal, a format
agentic-workspace owns. Reading it means knowing that format and reaching into
a container; neither is domain knowledge. The domain decides what the answer
MEANS (`phase_delegation.delegation_failure`); an adapter only reads it, already
normalised to `DelegationAttempt`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

# Imported at runtime, not under TYPE_CHECKING: the port re-exports the outcome
# it answers with, so an adapter needs nothing deeper than `ports`.
from syn_domain.contexts.agent_sessions import DelegationOutcome

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace

__all__ = [
    "DelegationAttempt",
    "DelegationEvidencePort",
    "DelegationEvidenceUnavailableError",
    "DelegationOutcome",
]


@dataclass(frozen=True)
class DelegationAttempt:
    """One delegate the phase's agent launched, as the platform observed it."""

    delegate_id: str
    """The journal's id for this child invocation."""
    target_harness: str
    """Which harness the work was delegated TO (``claude``, ``codex``)."""
    outcome: DelegationOutcome | None
    """How it ended; None when it launched and never reported an end."""
    exit_code: int | None = None
    reason: str | None = None
    """Why it could not launch, when the shim named a reason."""

    def describe(self) -> str:
        ended = self.outcome.value if self.outcome is not None else "never reported an outcome"
        detail = [f"exit_code={self.exit_code}"] if self.exit_code is not None else []
        if self.reason is not None:
            detail.append(f"reason={self.reason}")
        suffix = f" ({', '.join(detail)})" if detail else ""
        return f"delegate {self.delegate_id} -> {self.target_harness}: {ended}{suffix}"


class DelegationEvidenceUnavailableError(Exception):
    """The port could not read the delegation record for this workspace."""


class DelegationEvidencePort(Protocol):
    """Every cross-harness delegation a phase's workspace recorded.

    Satisfied by an adapter over agentic-workspace's child journal. Raises
    `DelegationEvidenceUnavailableError` when the record cannot be read; an
    empty tuple is a positive answer - "read it, nothing delegated".
    """

    async def attempts(self, workspace: ManagedWorkspace) -> tuple[DelegationAttempt, ...]: ...
