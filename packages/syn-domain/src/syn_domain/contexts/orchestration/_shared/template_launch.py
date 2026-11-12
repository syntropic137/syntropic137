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

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from event_sourcing import ConcurrencyConflictError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )
    from syn_domain.repository import Repository

logger = logging.getLogger(__name__)

# A launch with no stream and no recorded outcome after this long belongs to a
# process that died mid-start, and stops counting as active, so it cannot block
# an archive forever. A live start that fails records its outcome instead, so
# this is not a deadline any live start has to meet; it only has to outlast
# one, and it costs nothing but a delayed archive after a crash (#1635).
LAUNCH_BACKSTOP = timedelta(hours=24)

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


class ProjectionBarrier(Protocol):
    """Whether the execution projection has caught up with the store (#1588).

    Executions launched before launches were recorded on the template's
    stream have no record there, so only the projection knows them. It is
    trustworthy only once it has processed every event that existed when the
    question was asked: false means it may still be missing one.
    """

    async def projected_through_head(self) -> bool: ...


class TemplateLaunches:
    """Records each launch on the template's stream before the execution starts."""

    def __init__(self, repository: Repository[WorkflowTemplateAggregate]) -> None:
        self._repository = repository

    @asynccontextmanager
    async def launching(self, workflow_id: str, execution_id: str) -> AsyncIterator[None]:
        """Record the launch, then hold it until the start inside the block has an outcome.

        The block is the start. If it raises, the launch is recorded abandoned
        and the error propagates unchanged; an execution whose stream did open
        is still judged by its own status. Raises ``TemplateArchivedError``,
        before the block runs, if the template is archived.
        """
        await self.record(workflow_id, execution_id)
        try:
            yield
        except Exception:
            await self._abandon(workflow_id, execution_id)
            raise

    async def record(self, workflow_id: str, execution_id: str) -> None:
        """Record the launch, or raise ``TemplateArchivedError`` if the template is archived."""
        await self._retrying(
            workflow_id, lambda t: t.record_execution_launch(execution_id, datetime.now(UTC))
        )

    async def _abandon(self, workflow_id: str, execution_id: str) -> None:
        # Never masks the start's own error. If this write is lost too, the
        # launch is held until LAUNCH_BACKSTOP, exactly as after a crash.
        try:
            await self._retrying(
                workflow_id, lambda t: t.record_launch_abandoned(execution_id, datetime.now(UTC))
            )
        except Exception:
            logger.exception(
                "Could not record launch %s of %s abandoned; it holds archive until %s passes",
                execution_id,
                workflow_id,
                LAUNCH_BACKSTOP,
            )

    async def _retrying(
        self, workflow_id: str, decide: Callable[[WorkflowTemplateAggregate], None]
    ) -> None:
        for _ in range(_MAX_ATTEMPTS - 1):
            try:
                await self._write_once(workflow_id, decide)
            except ConcurrencyConflictError:
                continue
            return
        await self._write_once(workflow_id, decide)

    async def _write_once(
        self, workflow_id: str, decide: Callable[[WorkflowTemplateAggregate], None]
    ) -> None:
        template = await self._repository.get_by_id(workflow_id)
        if template is None:
            msg = f"Workflow {workflow_id} not found"
            raise TemplateArchivedError(msg)
        try:
            decide(template)
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
    exist yet is active, however long its start takes: that is exactly the
    execution that a read model has not seen. It stops being active once its
    start is recorded abandoned, or after ``LAUNCH_BACKSTOP`` if neither
    outcome was ever written.
    """
    active: list[str] = []
    abandoned = template.abandoned_launches
    for execution_id, launched_at in template.launches.items():
        execution = await executions.get_by_id(execution_id)
        if execution is None:
            if execution_id not in abandoned and now - launched_at < LAUNCH_BACKSTOP:
                active.append(execution_id)
        elif str(execution.status) in _ACTIVE_STATUSES:
            active.append(execution_id)
    return active
