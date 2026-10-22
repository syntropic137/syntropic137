"""What ``ExecutionHost`` drives, as the three things it needs done (ADR-072 D5).

Each is a Protocol so the loop is testable against doubles and so the real
implementations stay where their knowledge lives: the processor drains, the
workspace backend reaches and reaps, the aggregate decides whether a run can be
interrupted.
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
    """A workspace backend's reach, and its proof that a run's resources are gone (ADR-072 D3, D5, D13).

    Every resource the backend creates carries the owner's ``syn.host_id`` and
    the ``syn.execution_id`` at creation, so ``reap`` finds it by label and a
    create whose response was lost is still found.
    """

    def scope(self) -> str:
        """What this backend can reach: one Docker daemon, one provider account.

        Derived from the backend, never configured; raises when it cannot be read.
        """
        ...

    def provider(self) -> ProviderId: ...

    def isolation(self) -> IsolationLevel: ...

    async def reap(self, executor_id: str, execution_id: str) -> bool:
        """Remove every resource labelled with this owner and execution.

        True only when a listing shows none left. False, or a raise, keeps the
        run's slot charged: the host does not close it and the reconciler leaves
        it ``fencing`` and retries, the same rule as the startup reap's
        ``fully_reaped``.
        """
        ...


class RunInterrupter(Protocol):
    """Records a fenced run INTERRUPTED through its aggregate (ADR-072 D5 step 3).

    A run that is already terminal is left as it is, and that is not an error:
    the stalled owner may have finished, or interrupted itself, first.
    """

    async def interrupt(self, run: FencedRun) -> None: ...
