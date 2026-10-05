"""Launches and archives of a workflow template share one stream (#1588).

"Never archive a template with a running execution" spans two aggregates, so
neither can enforce it alone, and the execution projection cannot either: it
lags the store, so an execution that has started but is not yet projected
looked like no execution at all. Instead every launch is recorded on the
TEMPLATE's stream before the execution starts, and the archive reads those
launches back from the same stream. Both writes carry the version they read,
so a launch and an archive racing each other cannot both succeed: the second
to save conflicts, reloads, and decides again against the winner.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from event_sourcing import ConcurrencyConflictError

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )
    from syn_domain.repository import Repository

# A launch is recorded before its execution's stream exists. One with no stream
# after this long never started (its dispatch failed or the process died), and
# stops counting as active, so it cannot block an archive forever.
LAUNCH_GRACE = timedelta(minutes=10)

# Conflicts here are launches of the same template racing each other; each
# retry re-reads the stream, so a handful is plenty.
_MAX_ATTEMPTS = 5

_ACTIVE_STATUSES = frozenset({"running", "not_started"})


class TemplateArchivedError(ValueError):
    """The template was archived, so the launch is refused."""


class _Execution(Protocol):
    @property
    def status(self) -> str: ...


class ExecutionLookup(Protocol):
    """Loads an execution from its own stream: authoritative, never a read model."""

    async def get_by_id(self, aggregate_id: str) -> _Execution | None: ...


class TemplateLaunches:
    """Records each launch on the template's stream before the execution starts."""

    def __init__(self, repository: Repository[WorkflowTemplateAggregate]) -> None:
        self._repository = repository

    async def record(self, workflow_id: str, execution_id: str) -> None:
        """Record the launch, or raise ``TemplateArchivedError`` if the template is archived."""
        for _ in range(_MAX_ATTEMPTS - 1):
            try:
                await self._record_once(workflow_id, execution_id)
            except ConcurrencyConflictError:
                continue
            return
        await self._record_once(workflow_id, execution_id)

    async def _record_once(self, workflow_id: str, execution_id: str) -> None:
        template = await self._repository.get_by_id(workflow_id)
        if template is None:
            msg = f"Workflow {workflow_id} not found"
            raise TemplateArchivedError(msg)
        try:
            template.record_execution_launch(execution_id, datetime.now(UTC))
        except ValueError as e:
            raise TemplateArchivedError(str(e)) from None
        if template.get_uncommitted_events():
            await self._repository.save(template)
            template.mark_events_as_committed()


async def active_launches(
    template: WorkflowTemplateAggregate,
    executions: ExecutionLookup,
    now: datetime,
) -> list[str]:
    """The launches recorded on ``template`` whose execution is still active.

    Asked of each execution's own aggregate. A launch whose stream does not
    exist yet is active: that is exactly the execution that started a moment
    ago and that a read model has not seen.
    """
    active: list[str] = []
    for execution_id, launched_at in template.launches.items():
        execution = await executions.get_by_id(execution_id)
        if execution is None:
            if now - launched_at < LAUNCH_GRACE:
                active.append(execution_id)
        elif str(execution.status) in _ACTIVE_STATUSES:
            active.append(execution_id)
    return active
