"""What ``ExecutionHost`` drives, as the three things it needs done (ADR-072 D5).

Each is a Protocol so the loop is testable against doubles and so the real
implementations stay where their knowledge lives: the processor drains, the
container backend reaps, the aggregate decides whether a run can be interrupted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.ports import ClaimedRun, FencedRun, IsolationLevel


class ClaimedRunDrainer(Protocol):
    """Drains one claimed run to its end. ``WorkflowExecutionProcessor`` satisfies it.

    A cancel must take the shutdown interruption path (#1381) and re-raise.
    """

    async def run_claimed(self, claimed: ClaimedRun) -> object: ...


class RunReaper(Protocol):
    """The workspace backend, as reach and release (ADR-072 D3, D5, D6, D13).

    ``provider`` and ``isolation`` are what the backend actually runs, so
    the pool declares them from here and never from a setting. ``scope`` is
    what this backend can reach, derived from it and never
    configured: a reconciler fences only runs claimed in its own scope.
    ``reap`` removes every resource labelled ``syn.host_id=<executor_id>`` and
    ``syn.execution_id``, found by label and never by a handle a create call
    returned, so a create whose response was lost is still found. It returns
    True only when a listing shows none left. Nothing frees a slot until it
    does: not the owner's close, not the reconciler's ``close_interrupted``.
    """

    def scope(self) -> str: ...

    def provider(self) -> str: ...

    def isolation(self) -> IsolationLevel: ...

    async def reap(self, executor_id: str, execution_id: str) -> bool: ...


class RunInterrupter(Protocol):
    """Records a fenced run INTERRUPTED through its aggregate (ADR-072 D5 step 3).

    A run that is already terminal is left as it is, and that is not an error:
    the stalled owner may have finished, or interrupted itself, first.
    """

    async def interrupt(self, run: FencedRun) -> None: ...
