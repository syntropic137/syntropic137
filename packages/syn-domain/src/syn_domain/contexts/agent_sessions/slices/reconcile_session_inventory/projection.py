"""Replay only projects to-do state. Live processing dispatches leased work."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from event_sourcing import ProcessManager, ProjectionCheckpoint, ProjectionResult

from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationRequest,
    ReconciliationStage,
    ReconciliationState,
)
from syn_domain.contexts.agent_sessions.domain.events.InventoryReconciliationChangedEvent import (
    InventoryReconciliationChangedEvent,
)
from syn_domain.contexts.agent_sessions.domain.events.InventoryReconciliationSweepEvent import (
    InventoryReconciliationSweepEvent,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import RunIdentity
from syn_domain.contexts.agent_sessions.ports.SessionInventoryJobPort import (
    InventoryJob,
    InventoryStepOutcome,
)

if TYPE_CHECKING:
    from event_sourcing import (
        DispatchContext,
        DomainEvent,
        EventEnvelope,
        ProjectionCheckpointStore,
    )

    from syn_domain.contexts.agent_sessions.ports.SessionInventoryJobPort import (
        InventoryJobLease,
        SessionInventoryJobPort,
    )

    from .HostSessionEvidenceProjector import HostSessionEvidenceProjector

logger = logging.getLogger(__name__)


class InventoryWorkPort(Protocol):
    async def schedule(self) -> None: ...
    async def execute(self, lease: InventoryJobLease) -> InventoryStepOutcome: ...


def _log_stage(stage: str, started: float, job_id: str | None = None) -> None:
    # Per-stage wall time for #1528: which part of a tick is slow is measured,
    # not guessed. Debug level, so it costs nothing unless enabled.
    duration_ms = (time.perf_counter() - started) * 1000
    logger.debug(
        "Inventory process_pending stage %s took %.1f ms",
        stage,
        duration_ms,
        extra={"stage": stage, "job_id": job_id, "duration_ms": duration_ms},
    )


class InventoryReconciliationProcessManager(ProcessManager):
    PROJECTION_NAME = "session_inventory_jobs"
    # 2: replay execution terminal events into settlement evidence (#1398).
    VERSION = 2

    def __init__(
        self,
        jobs: SessionInventoryJobPort,
        work: InventoryWorkPort,
        *,
        lease_seconds: int,
        retry_seconds: int,
        max_jobs_per_tick: int,
        park_safety_seconds: int = 900,
        host_evidence: HostSessionEvidenceProjector | None = None,
    ) -> None:
        if (
            lease_seconds < 1
            or retry_seconds < 0
            or max_jobs_per_tick < 1
            or park_safety_seconds < 1
        ):
            raise ValueError("invalid inventory worker limits")
        self._jobs, self._work = jobs, work
        self._lease_seconds, self._retry_seconds = lease_seconds, retry_seconds
        self._park_safety_seconds = park_safety_seconds
        self._max_jobs = max_jobs_per_tick
        self._host_evidence = host_evidence

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_idempotency_key(self, todo_item: object) -> str:
        if not isinstance(todo_item, InventoryJob):
            raise TypeError("inventory processor requires a typed InventoryJob")
        return todo_item.job_id

    def get_version(self) -> int:
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str]:
        return {
            *(self._host_evidence.get_subscribed_event_types() if self._host_evidence else ()),
            InventoryReconciliationChangedEvent.event_type,
            InventoryReconciliationSweepEvent.event_type,
        }

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: ProjectionCheckpointStore,
        context: DispatchContext | None = None,  # noqa: ARG002
    ) -> ProjectionResult:
        # To-do writes only, as in the pre-existing SessionStarted/invocation
        # path this extends. The evidence journal is this process manager's
        # own durable to-do input (its outbox is what process_pending()
        # schedules from); spools, settlement deadlines and the latest
        # recorded clock time are its own to-do tables. Every write is keyed by
        # the source event's identity or the run, first-write-wins or
        # monotonic, so catch-up replay converges on the same rows. Nothing
        # pending is processed here: releasing due settlement deadlines,
        # scheduling and job execution all happen in process_pending(), which
        # the coordinator never calls while catching up.
        if self._host_evidence is not None:
            await self._host_evidence.handle(envelope)
        if envelope.metadata.event_type == InventoryReconciliationChangedEvent.event_type:
            event = InventoryReconciliationChangedEvent.model_validate_json(
                envelope.event.model_dump_json()
            )
            state = ReconciliationState(
                request=ReconciliationRequest(
                    run=RunIdentity(
                        source_instance_id=event.source_instance_id, execution_id=event.execution_id
                    ),
                    evidence_watermark=event.evidence_watermark,
                    expected_head=event.expected_head,
                    snapshot_id=event.snapshot_id,
                    resolver_version=event.resolver_version,
                ),
                stage=ReconciliationStage(event.stage),
                revision=event.revision,
                failure_code=event.failure_code,
            )
            await self._jobs.project(
                InventoryJob(
                    job_id=envelope.metadata.aggregate_id,
                    state=state,
                    global_position=envelope.metadata.global_nonce or 0,
                )
            )
        await checkpoint_store.save_checkpoint(
            ProjectionCheckpoint(
                projection_name=self.PROJECTION_NAME,
                global_position=envelope.metadata.global_nonce or 0,
                updated_at=datetime.now(UTC),
                version=self.VERSION,
            )
        )
        return ProjectionResult.SUCCESS

    async def process_pending(self) -> int:
        """Run due work; return how many steps ADVANCED. Idle returns 0 and emits nothing."""
        if self._host_evidence is not None:
            # Before scheduling, so a released deadline is reconciled this tick.
            started = time.perf_counter()
            await self._host_evidence.release_deadlines()
            _log_stage("release_deadlines", started)
        started = time.perf_counter()
        await self._work.schedule()
        _log_stage("schedule", started)
        processed = 0
        for _ in range(self._max_jobs):
            lease = await self._jobs.claim(lease_seconds=self._lease_seconds)
            if lease is None:
                break
            started = time.perf_counter()
            try:
                outcome = await self._work.execute(lease)
            except Exception:
                logger.exception(
                    "Inventory step failed; durable job remains retryable",
                    extra={"job_id": lease.job.job_id},
                )
                await self._jobs.release(lease, retry_seconds=self._retry_seconds)
                continue
            finally:
                _log_stage("execute", started, lease.job.job_id)
            # Either way the job's next step depends on an event this manager
            # has not projected yet: the one the step just saved, or the newer
            # one the store already holds. A timed retry would only re-claim
            # the same stale row (#1528), so wait for project() to re-arm it.
            await self._jobs.park(lease, safety_seconds=self._park_safety_seconds)
            if outcome is InventoryStepOutcome.ADVANCED:
                processed += 1
        return processed
