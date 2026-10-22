"""What ``ExecutionHost`` drives, as the three things it needs done (ADR-072 D5).

Each is a Protocol so the loop is testable against doubles and so the real
implementations stay where their knowledge lives: the processor drains, the
workspace backend reaps, the aggregate decides whether a run can be interrupted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.ports import (
        ClaimedRun,
        FencedRun,
        IsolationLevel,
        ProviderId,
    )


class ClaimedRunDrainer(Protocol):
    """Drains one claimed run to its end. ``WorkflowExecutionProcessor`` satisfies it.

    A cancel must take the shutdown interruption path (#1381) and re-raise.
    """

    async def run_claimed(self, claimed: ClaimedRun) -> object: ...


class RunReaper(Protocol):
    """The workspace backend's reach and release for one executor's run (ADR-072 D3, D5, D13).

    ``reap`` selects by ``syn.host_id=<executor_id>`` and ``syn.execution_id``,
    labels every resource carries from creation, never by a handle a create
    returned, so a create whose response was lost is still found, and a live
    host's resources are never touched. True only when a listing shows none
    left; False, or an exception, keeps the slot charged: the host leaves a
    finished run ``claimed`` for reconciliation, and a reconciler keeps a run
    ``fencing`` and retries it.
    """

    def scope(self) -> str:
        """What this backend can reach (the Docker engine ID); derived, never configured."""
        ...

    def provider(self) -> ProviderId: ...

    def isolation(self) -> IsolationLevel: ...

    async def reap(self, executor_id: str, execution_id: str) -> bool: ...


class RunInterrupter(Protocol):
    """Records a fenced run INTERRUPTED through its aggregate (ADR-072 D5 step 3).

    A run that is already terminal is left as it is, and that is not an error:
    the stalled owner may have finished, or interrupted itself, first.
    """

    async def interrupt(self, run: FencedRun) -> None: ...
