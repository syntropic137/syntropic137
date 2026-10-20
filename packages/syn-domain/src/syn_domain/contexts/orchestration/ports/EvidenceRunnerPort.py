"""Port for gathering evidence on the forge (plan §A.5, PR 5b).

docs/plans/20261015_platform-dispatched-evidence.md §A.5/§A.8. Dispatching a
target repository's `<kind>-evidence.yml`, finding its run and reading the
`evidence.json` it uploads all mean knowing a forge and its credentials, which
is not domain knowledge. The GitHub adapter lands in PR 6. Gathering evidence
and writing to a branch carry different trust, so the write is a separate port
(`RemoteBranchWriterPort`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime  # noqa: TC003 - a dataclass field type
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.orchestration._shared.evidence_contract import (
    EvidenceStepKind,  # noqa: TC001 - a dataclass field type
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.evidence_contract import EvidenceReport

__all__ = [
    "Accepted",
    "Ambiguous",
    "DispatchResult",
    "EvidenceAttemptRef",
    "EvidenceRunnerPort",
    "RefusalReason",
    "Refused",
    "RunConclusion",
    "RunRef",
]


@dataclass(frozen=True)
class EvidenceAttemptRef:
    """One recorded attempt, everything a runner needs to dispatch or find it."""

    repository: str
    kind: EvidenceStepKind
    pr: int | None
    #: The SHA the step runs against: S, or S' after the platform's removal.
    head_sha: str | None
    tests: tuple[str, ...]
    dispatch_id: str
    started_at: datetime


@dataclass(frozen=True)
class RunRef:
    run_id: int
    run_url: str


class RefusalReason(StrEnum):
    """Why the forge refused a dispatch; each settles `unavailable: <value>`."""

    PERMISSION = "permission"
    WORKFLOW_ABSENT = "workflow_absent"


@dataclass(frozen=True)
class Accepted:
    """The forge took the dispatch; ``run`` when it already named the run."""

    run: RunRef | None = None


@dataclass(frozen=True)
class Refused:
    reason: RefusalReason


@dataclass(frozen=True)
class Ambiguous:
    """Nobody knows whether the dispatch landed. Never re-POSTed straight away (§A.5 1)."""

    detail: str


DispatchResult = Accepted | Refused | Ambiguous


class RunConclusion(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    #: ``not_after`` passed while the run was still going.
    TIMED_OUT = "timed_out"


class EvidenceRunnerPort(Protocol):
    """Dispatches, finds, waits on and reads one evidence run. Implementations MUST NOT raise."""

    async def dispatch(self, attempt: EvidenceAttemptRef) -> DispatchResult: ...

    async def find_run(self, attempt: EvidenceAttemptRef) -> RunRef | None:
        """The run whose name carries ``attempt.dispatch_id``, paginating by time, not count (I2)."""
        ...

    async def await_run(self, run: RunRef, not_after: datetime) -> RunConclusion: ...

    async def await_check(
        self, repository: str, sha: str, check_name: str, not_after: datetime
    ) -> RunConclusion:
        """How the required check ``check_name`` concluded on ``sha`` (read-only, `checks: read`)."""
        ...

    async def fetch_report(self, run: RunRef) -> EvidenceReport | None:
        """The run's parsed `evidence.json`, or None when it uploaded none or it did not parse."""
        ...
