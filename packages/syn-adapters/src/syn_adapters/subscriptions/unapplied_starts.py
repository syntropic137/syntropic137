"""Executions whose start a read model claims to have processed but never applied.

WHY THIS EXISTS (#1545). `exec-db527ea0d361`'s WorkflowExecutionStarted was in
the store at global 39502, every projection checkpoint was at the head, nothing
was logged, and `GET /executions/{id}` returned 404 for 2h22m. Lag measurement
cannot see that: a projection whose checkpoint passed an event it never handled
looks exactly like one that handled it. The cause was the event store letting a
lower global nonce commit after a higher one, so the live subscription's cursor
passed it (fixed in event-sourcing-platform#337). The lesson is broader: any
drop below the checkpoint is silent by construction, so it has to be looked for.

WHAT COUNTS. A start is *unapplied* in a projection when every execution read
model's checkpoint is at or past the start event's global nonce and that read
model has no row for the execution with `started_at` set. A row without
`started_at` is the #598 failure-fallback row, which is exactly what #1545 left
behind. Above the checkpoints a missing row is ordinary lag (`read_model_lag`).

INCREMENTAL, WITH A SAFETY WINDOW. The detector keeps a high-water mark in
memory: the store position up to which every start has been judged. Each check
reads from `mark - safety_window` to the lowest checkpoint, at most
`max_events_per_check` events, and looks up only starts it has not already
confirmed, in batches of one query per read model. A check with nothing new
does no lookups. Unresolved findings are re-asked every check, so a repair
clears them without a restart. Restarting re-scans the store once, in bounded
steps.

- The window covers a start that becomes visible below the mark after the mark
  passed it, which is the #1545 mechanism. Since event-sourcing-platform#337
  the store commits in nonce order per tenant, so the window is a margin, not
  the guarantee.
- A row lost after its start was confirmed (a botched rebuild, a truncation)
  is found on the next restart's rescan, not before. Rebuilds go through the
  coordinator, which replays the whole stream.

NEVER A FINDING FROM A MOVING READ MODEL. A version rebuild clears a
projection's rows and deletes its checkpoint before replaying. Rows read during
that window are missing for a healthy reason. So a check judges nothing unless
the read path is settled (not catching up) and every checkpoint exists, and it
keeps nothing unless, after the rows were read, the read path is still
settled and no checkpoint disappeared or moved backwards (a forward move is
normal live progress). A check that fails those conditions returns None and
changes no state. A rebuild could still clear rows and replay past the
captured checkpoint between those two reads, so a start is reported only when
it is missing on two consecutive settled checks: a rebuild that completes
restores the row before the second one.

The detector never runs on the /health request path: `UnappliedStartWatch`
runs it in the background and /health reads the latest report.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.orchestration import WorkflowExecutionStartedEvent

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from event_sourcing import DomainEvent, EventEnvelope
    from event_sourcing.core.checkpoint import ProjectionCheckpointStore

logger = logging.getLogger(__name__)

_PAGE_SIZE: Final[int] = 500
#: Execution ids per read-model query.
LOOKUP_BATCH_SIZE: Final[int] = 500
#: Events re-read below the high-water mark on every check.
SAFETY_WINDOW: Final[int] = 1_000
#: Upper bound on events read by one check; a restart's rescan takes several.
MAX_EVENTS_PER_CHECK: Final[int] = 20_000
#: How often the watch checks. Bounds detection latency.
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

    async def applied_starts(self, execution_ids: Sequence[str]) -> set[str]:
        """The subset of `execution_ids` with a row carrying `started_at`. One query."""
        ...


class UnappliedStart(BaseModel):
    """One execution whose start a projection skipped past. Published on /health as is."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection: str = Field(description="Read model that skipped the start.")
    execution_id: str = Field(description="Execution whose WorkflowExecutionStarted it skipped.")
    global_nonce: int = Field(description="Store position of that start event.")


@dataclass(frozen=True, slots=True)
class UnappliedStartsReport:
    """What the detector has found so far, and how far into the store it has judged."""

    unapplied: tuple[UnappliedStart, ...]
    scanned_through: int


#: A start must be missing on this many consecutive settled checks to be reported.
CONFIRMING_SIGHTINGS: Final[int] = 2


@dataclass(frozen=True, slots=True)
class _Finding:
    """A start some read model lacked, and on how many consecutive checks."""

    nonce: int
    lacking: frozenset[str]
    sightings: int

    @property
    def published(self) -> bool:
        return self.sightings >= CONFIRMING_SIGHTINGS


@dataclass(frozen=True, slots=True)
class _Window:
    """The starts one check reads, and the position it read through."""

    starts: dict[str, int]
    read_through: int


class UnappliedStartDetector:
    """Finds WorkflowExecutionStarted events the read models' checkpoints passed without applying."""

    def __init__(
        self,
        event_store: _ReadsAllEvents,
        checkpoint_store: ProjectionCheckpointStore,
        projections: Sequence[AppliesExecutionStarts],
        *,
        is_settled: Callable[[], Awaitable[bool]],
        safety_window: int = SAFETY_WINDOW,
        max_events_per_check: int = MAX_EVENTS_PER_CHECK,
    ) -> None:
        self._event_store = event_store
        self._checkpoint_store = checkpoint_store
        self._projections = tuple(projections)
        self._is_settled = is_settled
        self._safety_window = safety_window
        self._max_events = max_events_per_check
        #: Every start at or below this position has been judged.
        self._mark = 0
        #: Starts confirmed in every read model, kept only while inside the window.
        self._confirmed: dict[str, int] = {}
        #: Unresolved findings by execution_id.
        self._open: dict[str, _Finding] = {}
        self._lock = asyncio.Lock()

    async def check(self) -> UnappliedStartsReport | None:
        """Judge the starts the read models have passed since the last check.

        None means the read path was moving, so nothing was judged and no state
        changed. The caller keeps its previous report.
        """
        async with self._lock:
            before = await self._checkpoints_if_settled()
            if before is None:
                return None
            window = await self._read_window(min(before.values()))
            candidates = {
                execution_id: nonce
                for execution_id, nonce in window.starts.items()
                if execution_id not in self._confirmed
            }
            candidates.update({eid: f.nonce for eid, f in self._open.items()})
            missing = await self._missing(candidates)
            after = await self._checkpoints_if_settled()
            if after is None or any(after[name] < before[name] for name in before):
                return None  # a rebuild or replay interleaved: the rows proved nothing
            self._commit(candidates, missing, window.read_through)
            return self._report()

    async def _checkpoints_if_settled(self) -> dict[str, int] | None:
        if not await self._is_settled():
            return None
        positions: dict[str, int] = {}
        for projection in self._projections:
            checkpoint = await self._checkpoint_store.get_checkpoint(projection.get_name())
            if checkpoint is None:
                return None  # cleared for a rebuild
            positions[projection.get_name()] = checkpoint.global_position
        return positions

    async def _read_window(self, through: int) -> _Window:
        starts: dict[str, int] = {}
        position = max(1, self._mark - self._safety_window + 1)
        last_read = self._mark
        # The budget counts only events past the mark: the window below it is
        # re-read every check and bounded by its own size, so it can never use
        # up the budget and stop the mark from advancing.
        budget = self._max_events
        while position <= through:
            if budget <= 0:
                # Out of budget: judged only as far as was read.
                return _Window(starts=starts, read_through=last_read)
            events, is_end, next_position = await self._event_store.read_all(
                from_global_nonce=position, max_count=min(_PAGE_SIZE, budget), forward=True
            )
            page_last, past_mark = self._absorb(events, through, starts)
            last_read = max(last_read, page_last)
            budget -= past_mark
            if is_end or not events or next_position <= position:
                break
            position = next_position
        return _Window(starts=starts, read_through=max(last_read, through))

    def _absorb(
        self,
        events: Sequence[EventEnvelope[DomainEvent]],
        through: int,
        starts: dict[str, int],
    ) -> tuple[int, int]:
        """Record the starts in one page. Returns (last nonce read, events past the mark)."""
        last_read = 0
        past_mark = 0
        for envelope in events:
            nonce = envelope.metadata.global_nonce
            if nonce is None or nonce > through:
                continue
            last_read = max(last_read, nonce)
            past_mark += nonce > self._mark
            event = envelope.event
            if isinstance(event, WorkflowExecutionStartedEvent):
                starts.setdefault(event.execution_id, nonce)
        return last_read, past_mark

    async def _missing(self, candidates: dict[str, int]) -> dict[str, frozenset[str]]:
        """execution_id -> read models lacking its start. One query per batch per model."""
        ids = sorted(candidates)
        lacking: dict[str, set[str]] = {}
        for projection in self._projections:
            for i in range(0, len(ids), LOOKUP_BATCH_SIZE):
                batch = ids[i : i + LOOKUP_BATCH_SIZE]
                applied = await projection.applied_starts(batch)
                for execution_id in batch:
                    if execution_id not in applied:
                        lacking.setdefault(execution_id, set()).add(projection.get_name())
        return {eid: frozenset(names) for eid, names in lacking.items()}

    def _commit(
        self,
        candidates: dict[str, int],
        missing: dict[str, frozenset[str]],
        read_through: int,
    ) -> None:
        for execution_id, nonce in candidates.items():
            lacking = missing.get(execution_id)
            if lacking is None:
                self._open.pop(execution_id, None)
                self._confirmed[execution_id] = nonce
                continue
            previous = self._open.get(execution_id)
            sightings = previous.sightings + 1 if previous is not None else 1
            finding = _Finding(nonce=nonce, lacking=lacking, sightings=sightings)
            self._open[execution_id] = finding
            if finding.published and (previous is None or not previous.published):
                for name in sorted(lacking):
                    logger.error(
                        "Read model %s passed WorkflowExecutionStarted for %s (global nonce "
                        "%d) without applying it. Its API reads will 404 or show no start. "
                        "Repair: rebuild the projection "
                        "(docs/runbooks/repair-dropped-execution-start.md).",
                        name,
                        execution_id,
                        nonce,
                    )
        self._mark = max(self._mark, read_through)
        floor = self._mark - self._safety_window
        self._confirmed = {eid: n for eid, n in self._confirmed.items() if n > floor}

    def _report(self) -> UnappliedStartsReport:
        unapplied = [
            UnappliedStart(projection=name, execution_id=execution_id, global_nonce=finding.nonce)
            for execution_id, finding in self._open.items()
            if finding.published
            for name in finding.lacking
        ]
        return UnappliedStartsReport(
            unapplied=tuple(sorted(unapplied, key=lambda u: (u.global_nonce, u.projection))),
            scanned_through=self._mark,
        )


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
                report = await self._detector.check()
                if report is not None:
                    self.latest = report
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unapplied-start check failed (#1545); retrying next interval")
            await asyncio.sleep(self._interval_seconds)
