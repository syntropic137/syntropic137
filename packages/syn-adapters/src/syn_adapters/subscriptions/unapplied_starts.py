"""Executions whose start a read model claims to have processed but never applied.

WHY THIS EXISTS (#1545). `exec-db527ea0d361`'s WorkflowExecutionStarted was in
the store at global 39502, every projection checkpoint was at the head, nothing
was logged, and `GET /executions/{id}` returned 404 for 2h22m. Lag measurement
cannot see that: a projection whose checkpoint passed an event it never handled
looks exactly like one that handled it. The cause was the event store letting a
lower global nonce commit after a higher one, so the live subscription's cursor
passed it (fixed in event-sourcing-platform#337). The lesson is broader: any
drop below the checkpoint is silent by construction, so it has to be looked for.

WHAT COUNTS. A start is *unapplied* in a projection when the projection's
checkpoint is at or past the start event's global nonce and
`has_applied_start(execution_id)` is still False. Below the checkpoint the
projection has said "done"; above it, a missing row is ordinary lag and is not
reported here (`read_model_lag` reports that).

EVERY CHECK IS A COMPLETE RECONCILIATION. Each check rescans the store from 0
and asks about every start again; nothing is remembered between checks except
which drops were already logged. Both shortcuts an incremental scan would take
are unsound here:

- A cursor that advances past the highest nonce it has read never revisits a
  lower nonce that commits later. That late commit IS #1545's mechanism, so an
  incremental detector misses exactly the drop it exists to report.
  `global_nonce` also has permanent gaps (rolled-back appends), so there is no
  gap-free prefix to advance through.
- Forgetting a start once its row was seen means a row lost LATER (a botched
  rebuild, a truncation, another handler defect) is never reported.

COST. One paged read of the store plus one keyed lookup per start per read
model, on `CHECK_INTERVAL_SECONDS`. It never runs on the /health request path:
`UnappliedStartWatch` runs it in the background and /health reads the latest
report.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from event_sourcing import DomainEvent, EventEnvelope
    from event_sourcing.core.checkpoint import ProjectionCheckpointStore

logger = logging.getLogger(__name__)

_PAGE_SIZE: Final[int] = 500

#: How often the watch reconciles. Bounds both detection latency and cost.
CHECK_INTERVAL_SECONDS: Final[float] = 300.0


class _ReadsAllEvents(Protocol):
    async def read_all(
        self,
        from_global_nonce: int = 0,
        max_count: int = 100,
        forward: bool = True,
    ) -> tuple[list[EventEnvelope[DomainEvent]], bool, int]: ...


@runtime_checkable
class AppliesExecutionStarts(Protocol):
    """A read model that must hold every started execution."""

    def get_name(self) -> str: ...

    async def has_applied_start(self, execution_id: str) -> bool: ...


class UnappliedStart(BaseModel):
    """One execution whose start a projection skipped past. Published on /health as is."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection: str = Field(description="Read model that skipped the start.")
    execution_id: str = Field(description="Execution whose WorkflowExecutionStarted it skipped.")
    global_nonce: int = Field(description="Store position of that start event.")


@dataclass(frozen=True, slots=True)
class UnappliedStartsReport:
    """What one complete reconciliation found, and how far into the store it read."""

    unapplied: tuple[UnappliedStart, ...]
    scanned_through: int


class UnappliedStartDetector:
    """Finds WorkflowExecutionStarted events a projection's checkpoint passed without applying."""

    def __init__(
        self,
        event_store: _ReadsAllEvents,
        checkpoint_store: ProjectionCheckpointStore,
        projections: Sequence[AppliesExecutionStarts],
    ) -> None:
        self._event_store = event_store
        self._checkpoint_store = checkpoint_store
        self._projections = tuple(projections)
        #: Only de-duplicates the error log. Never consulted for the answer.
        self._logged: set[tuple[str, str]] = set()
        self._lock = asyncio.Lock()

    async def check(self) -> UnappliedStartsReport:
        """Reconcile every start the projections' checkpoints cover, from nonce 0."""
        async with self._lock:
            # Checkpoints first: every start at or below one was offered to that
            # projection before this check began, whatever the scan reads next.
            covered = {p.get_name(): await self._covered(p) for p in self._projections}
            starts, scanned_through = await self._starts_through(max(covered.values(), default=0))
            unapplied: list[UnappliedStart] = []
            for projection in self._projections:
                name = projection.get_name()
                for execution_id, nonce in starts:
                    if nonce > covered[name]:
                        continue
                    if not await projection.has_applied_start(execution_id):
                        unapplied.append(
                            UnappliedStart(
                                projection=name, execution_id=execution_id, global_nonce=nonce
                            )
                        )
            self._log_new(unapplied, covered)
        return UnappliedStartsReport(
            unapplied=tuple(sorted(unapplied, key=lambda u: (u.global_nonce, u.projection))),
            scanned_through=scanned_through,
        )

    async def _covered(self, projection: AppliesExecutionStarts) -> int:
        checkpoint = await self._checkpoint_store.get_checkpoint(projection.get_name())
        return checkpoint.global_position if checkpoint is not None else 0

    async def _starts_through(self, through: int) -> tuple[list[tuple[str, int]], int]:
        """(execution_id, nonce) of every start at or below `through`, first start wins."""
        seen: set[str] = set()
        starts: list[tuple[str, int]] = []
        scanned_through = 0
        position = 0
        while position <= through:
            events, is_end, next_position = await self._event_store.read_all(
                from_global_nonce=position, max_count=_PAGE_SIZE, forward=True
            )
            for envelope in events:
                nonce = envelope.metadata.global_nonce
                if nonce is None or nonce > through:
                    continue
                scanned_through = max(scanned_through, nonce)
                event = envelope.event
                if (
                    isinstance(event, WorkflowExecutionStartedEvent)
                    and event.execution_id not in seen
                ):
                    seen.add(event.execution_id)
                    starts.append((event.execution_id, nonce))
            if is_end or not events or next_position <= position:
                break
            position = next_position
        return starts, scanned_through

    def _log_new(self, unapplied: list[UnappliedStart], covered: dict[str, int]) -> None:
        current = {(u.projection, u.execution_id) for u in unapplied}
        for drop in unapplied:
            if (drop.projection, drop.execution_id) in self._logged:
                continue
            logger.error(
                "Read model %s is checkpointed at %d but never applied "
                "WorkflowExecutionStarted for %s (global nonce %d). Its API reads "
                "will 404 or show no start. Repair: rebuild the projection "
                "(docs/runbooks/repair-dropped-execution-start.md).",
                drop.projection,
                covered[drop.projection],
                drop.execution_id,
                drop.global_nonce,
            )
        # A repaired drop that comes back is logged again.
        self._logged = current


class UnappliedStartWatch:
    """Runs the detector in the background; /health reads `latest`.

    Read-only: it reports, it never repairs. Repair is a projection rebuild,
    which is an operator decision. A failed check is logged and retried on the
    next tick, because a watch that dies on the first transient store error is
    a detector nobody notices is gone.
    """

    def __init__(
        self,
        detector: UnappliedStartDetector,
        *,
        interval_seconds: float = CHECK_INTERVAL_SECONDS,
    ) -> None:
        self._detector = detector
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        #: None until the first check completes: "not measured", not "healthy".
        self.latest: UnappliedStartsReport | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="unapplied-start-watch")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                self.latest = await self._detector.check()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unapplied-start check failed (#1545); retrying next interval")
            await asyncio.sleep(self._interval_seconds)
