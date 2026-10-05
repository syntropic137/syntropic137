"""Port for reading which delegates a phase's workspace launched, and how they ended (#894).

WHY THIS IS A PORT. A declared delegation is checked against the record the
delegate itself wrote - the workspace's child journal, a format
agentic-workspace owns. Reading it means knowing that format and reaching into
a container; neither is domain knowledge. The domain decides what the answer
MEANS (`phase_delegation.delegation_failure`); an adapter only reads it, already
normalised to `DelegationAttempt`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

# Imported at runtime, not under TYPE_CHECKING: the port re-exports what it
# answers with, so an adapter needs nothing deeper than `ports`. The attempt is
# also what a failed phase records (`DelegationFailure`), so it lives with the
# aggregate's value objects.
from syn_domain.contexts.agent_sessions import DelegationOutcome
from syn_domain.contexts.orchestration.domain.aggregate_execution.delegation_failure import (
    DelegationAttempt,
)

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace

__all__ = [
    "DelegationAttempt",
    "DelegationEvidencePort",
    "DelegationEvidenceUnavailableError",
    "DelegationOutcome",
]


class DelegationEvidenceUnavailableError(Exception):
    """The port could not read the delegation record for this workspace."""


class DelegationEvidencePort(Protocol):
    """Every cross-harness delegation a phase's workspace recorded.

    Satisfied by an adapter over agentic-workspace's child journal. Raises
    `DelegationEvidenceUnavailableError` when the record cannot be read; an
    empty tuple is a positive answer - "read it, nothing delegated".
    """

    async def attempts(self, workspace: ManagedWorkspace) -> tuple[DelegationAttempt, ...]: ...
