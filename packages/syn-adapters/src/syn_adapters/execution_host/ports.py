"""What ``ExecutionHost`` drives, as the three things it needs done (ADR-072 D5).

Each is a Protocol so the loop is testable against doubles and so the real
implementations stay where their knowledge lives: the processor drains, the
container backend reaps, the aggregate decides whether a run can be interrupted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.ports import ClaimedRun, FencedRun


class ClaimedRunDrainer(Protocol):
    """Drains one claimed run to its end. ``WorkflowExecutionProcessor`` satisfies it.

    A cancel must take the shutdown interruption path (#1381) and re-raise.
    """

    async def run_claimed(self, claimed: ClaimedRun) -> object: ...


class DeadHostReaper(Protocol):
    """Removes the containers a dead executor left for one execution (ADR-072 D5, D6).

    Selects by ``syn.host_id=<run.executor_id>`` and ``syn.execution_id``, never
    by name alone, so a live host's containers are never touched. Returns
    whether the reap is shown complete; False keeps the run ``fencing`` and the
    reconciler retries it, the same rule as the startup reap's ``fully_reaped``.
    """

    async def reap(self, run: FencedRun) -> bool: ...


class RunInterrupter(Protocol):
    """Records a fenced run INTERRUPTED through its aggregate (ADR-072 D5 step 3).

    A run that is already terminal is left as it is, and that is not an error:
    the stalled owner may have finished, or interrupted itself, first.
    """

    async def interrupt(self, run: FencedRun) -> None: ...
