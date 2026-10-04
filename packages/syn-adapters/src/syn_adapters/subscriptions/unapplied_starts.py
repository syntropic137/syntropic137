"""Executions whose start a read model claims to have processed but never applied.

WHY THIS EXISTS (#1545). `exec-db527ea0d361`'s WorkflowExecutionStarted was in
the store at global 39502, every projection checkpoint was at the head, nothing
was logged, and `GET /executions/{id}` returned 404 for 2h22m. Lag measurement
cannot see that: a projection whose checkpoint passed an event it never handled
looks exactly like one that handled it. The cause was a store that could make a
lower nonce visible after a higher one (ESP ADR-026), but the lesson is broader:
any drop below the checkpoint is silent by construction, so it has to be looked
for.

WHAT COUNTS. A start is *unapplied* in a projection when the projection's
checkpoint is at or past the start event's global nonce and
`has_applied_start(execution_id)` is still False. Below the checkpoint the
projection has said "done"; above it, a missing row is ordinary lag and is not
reported here (`read_model_lag` reports that).

COST. Incremental: each `check()` reads at most `max_events_per_check` new
events from where the last one stopped, and asks each projection about a start
once, the first time its checkpoint covers it. A start that was applied is
forgotten; an unapplied one stays and is re-asked on every check, so a repair
(rebuild or replay) clears it without a restart. The first checks after a
restart walk the store in bounded steps; `scanned_through` says how far.

Held in memory on purpose: everything here is re-derivable from the store and
the projections, so a restart costs a re-scan, never a wrong answer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from event_sourcing import EventStoreClient
    from event_sourcing.core.checkpoint import ProjectionCheckpointStore

logger = logging.getLogger(__name__)

_DEFAULT_MAX_EVENTS_PER_CHECK = 5_000
_PAGE_SIZE = 500


class AppliesExecutionStarts(Protocol):
    """A read model that must hold every started execution."""

    def get_name(self) -> str: ...

    async def has_applied_start(self, execution_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class UnappliedStart:
    """One execution whose start a projection skipped past."""

    projection: str
    execution_id: str
    global_nonce: int


@dataclass(frozen=True, slots=True)
class UnappliedStartsReport:
    """What one check found, and how much of the store it has seen so far."""

    unapplied: tuple[UnappliedStart, ...]
    scanned_through: int


class UnappliedStartDetector:
    """Finds WorkflowExecutionStarted events a projection's checkpoint passed without applying."""

    def __init__(
        self,
        event_store: EventStoreClient,
        checkpoint_store: ProjectionCheckpointStore,
        projections: Sequence[AppliesExecutionStarts],
        *,
        max_events_per_check: int = _DEFAULT_MAX_EVENTS_PER_CHECK,
    ) -> None:
        self._event_store = event_store
        self._checkpoint_store = checkpoint_store
        self._projections = tuple(projections)
        self._max_events_per_check = max_events_per_check
        self._next_nonce = 0
        self._scanned_through = 0
        #: Per projection: execution_id -> nonce of a start not yet confirmed applied.
        self._unconfirmed: dict[str, dict[str, int]] = {p.get_name(): {} for p in self._projections}
        self._reported: set[tuple[str, str]] = set()

    async def check(self) -> UnappliedStartsReport:
        """Scan forward, then ask each projection about the starts its checkpoint covers."""
        await self._scan()
        unapplied: list[UnappliedStart] = []
        for projection in self._projections:
            unapplied.extend(await self._unapplied_in(projection))
        return UnappliedStartsReport(
            unapplied=tuple(sorted(unapplied, key=lambda u: (u.global_nonce, u.projection))),
            scanned_through=self._scanned_through,
        )

    async def _scan(self) -> None:
        budget = self._max_events_per_check
        while budget > 0:
            events, is_end, next_nonce = await self._event_store.read_all(
                from_global_nonce=self._next_nonce,
                max_count=min(_PAGE_SIZE, budget),
                forward=True,
            )
            for envelope in events:
                nonce = envelope.metadata.global_nonce
                if nonce is None:
                    continue
                self._scanned_through = max(self._scanned_through, nonce)
                if isinstance(envelope.event, WorkflowExecutionStartedEvent):
                    for pending in self._unconfirmed.values():
                        pending[envelope.event.execution_id] = nonce
            budget -= len(events)
            if events:
                self._next_nonce = max(next_nonce, self._scanned_through + 1)
            if is_end or not events:
                return

    async def _unapplied_in(self, projection: AppliesExecutionStarts) -> list[UnappliedStart]:
        name = projection.get_name()
        checkpoint = await self._checkpoint_store.get_checkpoint(name)
        covered = checkpoint.global_position if checkpoint is not None else 0
        pending = self._unconfirmed[name]
        found: list[UnappliedStart] = []
        for execution_id, nonce in list(pending.items()):
            if nonce > covered:
                continue
            if await projection.has_applied_start(execution_id):
                del pending[execution_id]
                self._reported.discard((name, execution_id))
                continue
            found.append(UnappliedStart(name, execution_id, nonce))
            if (name, execution_id) not in self._reported:
                self._reported.add((name, execution_id))
                logger.error(
                    "Read model %s is checkpointed at %d but never applied "
                    "WorkflowExecutionStarted for %s (global nonce %d). Its API reads "
                    "will 404 or show no start. Repair: rebuild the projection "
                    "(docs/runbooks/repair-dropped-execution-start.md).",
                    name,
                    covered,
                    execution_id,
                    nonce,
                )
        return found
