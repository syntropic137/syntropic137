"""Detect executions whose WorkflowExecutionStarted never reached the read models (#1545).

WHY THIS EXISTS. A read model that silently misses an event raises nothing:
the checkpoint is at the head, the lag probe says 0, and the API 404s a
running execution. #1545 was one of those - the start event was in the store
at global nonce 39502, both execution projections never applied it, and the
first anyone knew was an operator dispatching a duplicate. The root cause was
fixed in the event store (a live subscriber could skip a nonce whose append
committed after a higher one), but "the subscription delivers every event" is
a claim, and this is the check that keeps it honest.

WHAT IT CHECKS. Every `WorkflowExecutionStarted` in the store whose position
both execution projections have already passed must have produced a row in
each of them WITH `started_at` set. `started_at` is required on the event, so
a row without it is proof the start was never applied - that is exactly the
degraded row #1545 left behind, which a plain "row exists" check would pass
once the terminal handler had upserted it (#598's fallback).

Positions not yet passed are not judged: that is lag, and lag already has its
own probe. The scan is incremental - each call reads only the events appended
since the last one - so it can run on a timer against a store of any size.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from syn_domain.contexts.orchestration.slices.get_execution_detail import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions import (
    WorkflowExecutionListProjection,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from event_sourcing import DomainEvent, EventEnvelope

    from syn_adapters.subscriptions.coordinator_service import CoordinatorSubscriptionService
    from syn_adapters.subscriptions.read_model_lag import ReadModelLag

logger = logging.getLogger(__name__)

STARTED_EVENT_TYPE: Final[str] = "WorkflowExecutionStarted"
_PAGE_SIZE: Final[int] = 500


class _ReadsAllEvents(Protocol):
    async def read_all(
        self,
        from_global_nonce: int = 0,
        max_count: int = 100,
        forward: bool = True,
    ) -> tuple[list[EventEnvelope[DomainEvent]], bool, int]: ...


class _HasStartedAt(Protocol):
    @property
    def started_at(self) -> object: ...


@dataclass(frozen=True, slots=True)
class UnprojectedExecutions:
    """The result of one check.

    `execution_ids` are executions whose start is in the store at or below
    `checked_through` but is missing from at least one execution read model.
    Empty is the healthy answer.
    """

    execution_ids: tuple[str, ...]
    checked_through: int

    def describe(self) -> str | None:
        """An operator-facing warning, or None when nothing is missing."""
        if not self.execution_ids:
            return None
        shown = ", ".join(self.execution_ids[:10])
        more = len(self.execution_ids) - 10
        suffix = f" and {more} more" if more > 0 else ""
        return (
            f"{len(self.execution_ids)} execution(s) have a WorkflowExecutionStarted event "
            f"in the store that the execution read models never applied: {shown}{suffix}. "
            "The API will 404 or show them without a start. Rebuild the execution "
            "projections to repair (see docs/runbooks/read-model-dropped-event.md)."
        )


class UnprojectedExecutionDetector:
    """Finds started executions the execution read models do not reflect.

    Holds a cursor into the store and the set of starts it has seen but not yet
    confirmed, so each `check` costs the events appended since the previous one
    plus one lookup per unconfirmed start. A start that is confirmed is never
    looked up again; one that is missing stays listed until it is repaired.
    """

    def __init__(
        self,
        event_store: _ReadsAllEvents,
        lookups: tuple[Callable[[str], Awaitable[_HasStartedAt | None]], ...],
    ) -> None:
        self._event_store = event_store
        self._lookups = lookups
        self._next_position = 0
        # execution_id -> global nonce of its start event
        self._unconfirmed: dict[str, int] = {}

    async def check(self, settled_through: int) -> UnprojectedExecutions:
        """Report starts at or below `settled_through` that some read model lacks.

        `settled_through` is the lowest checkpoint among the execution
        projections: every event at or below it has been offered to them.
        """
        await self._read_new_starts()
        missing: list[str] = []
        for execution_id, position in sorted(self._unconfirmed.items(), key=lambda kv: kv[1]):
            if position > settled_through:
                continue
            if await self._is_projected(execution_id):
                del self._unconfirmed[execution_id]
            else:
                missing.append(execution_id)
        return UnprojectedExecutions(execution_ids=tuple(missing), checked_through=settled_through)

    async def _read_new_starts(self) -> None:
        while True:
            events, is_end, next_position = await self._event_store.read_all(
                from_global_nonce=self._next_position,
                max_count=_PAGE_SIZE,
                forward=True,
            )
            for envelope in events:
                self._record(envelope)
            if is_end or not events:
                return
            self._next_position = max(self._next_position, next_position)

    def _record(self, envelope: EventEnvelope[DomainEvent]) -> None:
        position = envelope.metadata.global_nonce
        if position is None:
            return
        self._next_position = max(self._next_position, position + 1)
        if envelope.metadata.event_type != STARTED_EVENT_TYPE:
            return
        execution_id = getattr(envelope.event, "execution_id", None)
        if isinstance(execution_id, str) and execution_id:
            self._unconfirmed.setdefault(execution_id, position)

    async def _is_projected(self, execution_id: str) -> bool:
        for lookup in self._lookups:
            row = await lookup(execution_id)
            if row is None or row.started_at is None:
                return False
        return True


#: The two read models a started execution must appear in. Named here, not
#: looked up, because "an execution the API can serve" is defined by these two.
EXECUTION_PROJECTIONS: Final[tuple[str, ...]] = (
    WorkflowExecutionListProjection.PROJECTION_NAME,
    WorkflowExecutionDetailProjection.PROJECTION_NAME,
)

#: How often the watcher re-checks. Each check reads only what was appended
#: since the previous one, so this bounds detection latency, not cost.
CHECK_INTERVAL_SECONDS: Final[float] = 300.0


def settled_position(lag: ReadModelLag) -> int:
    """The highest position both execution projections have passed.

    A projection absent from `lagging_projections` is at the head.
    """
    behind = {p.projection: p.position for p in lag.lagging_projections}
    return min(behind.get(name, lag.head_position) for name in EXECUTION_PROJECTIONS)


async def watch_unprojected_executions(
    subscription_service: CoordinatorSubscriptionService,
    detector: UnprojectedExecutionDetector,
    publish: Callable[[UnprojectedExecutions], None],
    interval_seconds: float = CHECK_INTERVAL_SECONDS,
) -> None:
    """Run `detector` forever, publishing each result and logging any drop.

    Read-only: it reports, it never repairs. Repair is a projection rebuild,
    which is an operator decision. A failed check is logged and retried on the
    next tick rather than ending the loop, because a watcher that dies on the
    first transient store error is a detector nobody notices is gone.
    """
    while True:
        try:
            lag = await subscription_service.describe_read_model_lag()
            if lag is not None:
                result = await detector.check(settled_position(lag))
                publish(result)
                warning = result.describe()
                if warning is not None:
                    logger.error("Read model drift (#1545): %s", warning)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unprojected-execution check failed; retrying next interval")
        await asyncio.sleep(interval_seconds)


@dataclass(slots=True)
class UnprojectedExecutionWatch:
    """Owns the watcher task and its latest result for the API lifecycle.

    The API holds exactly one, behind the module functions below, the same
    shape as `inventory_lifecycle`: lifecycle.py carries one call per hook
    (start, stop, warnings) and none of the wiring.
    """

    latest: UnprojectedExecutions | None = None
    _task: asyncio.Task[None] | None = None

    def start(self, subscription_service: CoordinatorSubscriptionService | None) -> None:
        """Start watching; a no-op if already running or there is no read path.

        Nothing to watch without a subscription: the detector judges events
        the execution projections have already passed, and only the
        subscription can say where that is.
        """
        if self._task is not None or subscription_service is None:
            return
        from syn_adapters.storage.event_store_client import get_event_store_client
        from syn_api._wiring import get_projection_mgr

        projections = get_projection_mgr()
        detector = UnprojectedExecutionDetector(
            get_event_store_client(),
            lookups=(
                projections.workflow_execution_list.get_by_id,
                projections.workflow_execution_detail.get_by_id,
            ),
        )
        self._task = asyncio.create_task(
            watch_unprojected_executions(subscription_service, detector, self._publish),
            name="unprojected-execution-watch",
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    def warnings(self) -> list[str]:
        """The /health warning for the latest result, if it found anything."""
        warning = self.latest.describe() if self.latest is not None else None
        return [warning] if warning is not None else []

    def _publish(self, result: UnprojectedExecutions) -> None:
        self.latest = result


_watch = UnprojectedExecutionWatch()


def start_watch(subscription_service: CoordinatorSubscriptionService | None) -> None:
    """Start the API's watch once the subscription coordinator is running.

    Never raises: it is called from the coordinator's own startup, and a
    detector that could fail that startup would degrade the read path it
    exists to watch.
    """
    try:
        _watch.start(subscription_service)
    except Exception:
        logger.exception("Unprojected-execution watch did not start (#1545); drift goes unreported")


async def stop_watch() -> None:
    await _watch.stop()


def health_warnings() -> list[str]:
    """The /health warnings for the latest check; empty when nothing is missing."""
    return _watch.warnings()
