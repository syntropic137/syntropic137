"""What GET /executions/{id} answers for an accepted start with no execution yet (#1557).

Two sources, in order. The execution budget knows where a start held in THIS
process stands - its queue position, or that it holds a slot. The request
start to-do record is durable: it is there after a restart, before any process
holds the start again, and it says how the last attempt went. Neither is a
read model of the execution, which does not exist until its stream opens.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_api._wiring_admission import get_execution_budget
from syn_api.execution_budget import StartPath
from syn_api.types import PhaseProgressInfo
from syn_domain.contexts.orchestration import (
    OWED_STATUSES,
    ExecutionRequestStartProcessManager,
    ExecutionRequestStartRecord,
    FailureClassification,
    PhaseProgress,
    read_start_record,
)

from .models import ExecutionDetailResponse, ExecutionStartQueueInfo, ExecutionSummaryResponse

if TYPE_CHECKING:
    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
    from syn_adapters.projections.manager import ProjectionManager
    from syn_api.execution_budget import StartPosition


def start_queue_info(
    position: StartPosition | None, record: ExecutionRequestStartRecord | None = None
) -> ExecutionStartQueueInfo | None:
    """A budget position and/or a durable request record, as the API states them."""
    budget = get_execution_budget()
    if position is not None:
        return ExecutionStartQueueInfo(
            path=position.claim.path,
            position=position.position,
            held=True,
            running=position.running,
            waiting=position.waiting,
            limit=position.limit,
            queued_at=position.claim.claimed_at,
            start_status=record.status if record is not None else None,
            status_reason=record.status_reason if record is not None else None,
        )
    if record is None:
        return None
    return ExecutionStartQueueInfo(
        path=StartPath.DIRECT,
        position=None,
        held=False,
        running=budget.running,
        waiting=budget.waiting,
        limit=budget.limit,
        queued_at=record.recorded_at,
        start_status=record.status,
        status_reason=record.status_reason,
    )


async def _request_record(
    store: ProjectionStoreProtocol, execution_id: str
) -> ExecutionRequestStartRecord | None:
    row = await store.get(ExecutionRequestStartProcessManager.PROJECTION_NAME, execution_id)
    return read_start_record(ExecutionRequestStartRecord, row) if row is not None else None


def _status(position: StartPosition | None, record: ExecutionRequestStartRecord | None) -> str:
    if record is not None and record.status == "withdrawn":
        # #1650: whatever the budget still holds, it gives back without starting.
        return "cancelled"
    if position is not None:
        return "queued" if position.queued else "starting"
    assert record is not None
    if record.status in OWED_STATUSES:
        return "queued"
    return "failed" if record.status == "failed" else "starting"


def _error_message(
    position: StartPosition | None, record: ExecutionRequestStartRecord | None
) -> str | None:
    """Why it did not start: a settled failure, or the reason it was withdrawn."""
    if record is None:
        return None
    settled = record.status == "withdrawn" or (position is None and record.status == "failed")
    return record.status_reason if settled else None


async def _find(
    store: ProjectionStoreProtocol, execution_id: str
) -> tuple[str, str, ExecutionRequestStartRecord | None] | None:
    """The full id, workflow id and durable record of a start, by id or prefix."""
    matches = get_execution_budget().matching(execution_id)
    claim = matches[0].claim if len(matches) == 1 else None
    full_id = claim.execution_id if claim is not None else execution_id
    record = await _request_record(store, full_id)
    if claim is not None:
        return full_id, claim.workflow_id, record
    if record is None:
        record = await _from_the_request_stream(full_id)
    if record is not None:
        return full_id, record.workflow_id, record
    return None


async def _from_the_request_stream(execution_id: str) -> ExecutionRequestStartRecord | None:
    """The request itself, when the to-do list has not projected it yet.

    After a 200 and a restart, or on another API process, the coordinator may
    not have delivered `ExecutionRequested` yet. The stream is authoritative and
    already written, so the start is reported `pending` from it rather than 404
    (codex review 3 of #1574; never treat a lagging projection as the truth).
    """
    if not execution_id.startswith("exec-"):
        return None
    from syn_adapters.storage.repositories import get_execution_request_repository
    from syn_domain.contexts.orchestration import execution_request_id

    request = await get_execution_request_repository().get_by_id(execution_request_id(execution_id))
    if request is None or request.workflow_id is None or request.requested_at is None:
        return None
    return ExecutionRequestStartRecord(
        execution_id=execution_id,
        workflow_id=request.workflow_id,
        recorded_at=request.requested_at,
        status="withdrawn" if request.withdrawn else "pending",
    )


async def queued_execution_id(mgr: ProjectionManager, execution_id: str) -> str | None:
    """The full id of an accepted start that has no execution yet, or None (#1650).

    None too once its record says it started: the execution exists, and only
    its read model is behind.
    """
    found = await _find(mgr.store, execution_id)
    if found is None or (found[2] is not None and found[2].status == "started"):
        return None
    return found[0]


async def not_yet_started(
    mgr: ProjectionManager, execution_id: str
) -> ExecutionDetailResponse | None:
    """The detail of an accepted start that has no execution record yet.

    Answering 404 for it told an operator who had just been handed its id that
    it did not exist, for as long as the runs ahead of it took - and, before the
    request was durable, for ever once the API restarted.
    """
    budget = get_execution_budget()
    found = await _find(mgr.store, execution_id)
    if found is None:
        return None
    full_id, workflow_id, record = found
    workflow = await mgr.workflow_detail.get_by_id(workflow_id)
    # Read the position AFTER the awaits: the start may have taken a slot, or
    # finished and released its claim, meanwhile.
    position = budget.position(full_id)
    if position is None and record is None:
        return None
    return ExecutionDetailResponse(
        workflow_execution_id=full_id,
        workflow_id=workflow_id,
        workflow_name=workflow.name if workflow is not None else "",
        status=_status(position, record),
        # Every read-model field, stated empty on purpose: a queued start has
        # no read model yet, and this says so rather than defaulting silently.
        started_at=None,
        completed_at=None,
        phases=[],
        total_phases=0,
        completed_phases=0,
        phase_plan=[],
        phase_progress=PhaseProgressInfo.of(
            PhaseProgress(status=_status(position, record), completed=0, skipped=0, defined=0)
        ),
        artifact_ids=[],
        error_message=_error_message(position, record),
        failure_classification=FailureClassification.UNCLASSIFIED,
        reported_failure_reason=None,
        repos=[],
        tags=[],
        total_duration_seconds=None,
        inputs={},
        total_input_tokens=0,
        total_output_tokens=0,
        total_cache_creation_tokens=0,
        total_cache_read_tokens=0,
        total_tokens=0,
        review_verdict=None,
        delegation_failure=None,
        quarantined_refs=[],
        start_queue=start_queue_info(position, record),
    )


@dataclass(frozen=True)
class QueuedStart:
    """One accepted start the execution list reports as ``queued`` (PC-124)."""

    execution_id: str
    workflow_id: str
    queue: ExecutionStartQueueInfo

    def as_summary(self, workflow_name: str) -> ExecutionSummaryResponse:
        """The list row: no read model yet, so every read-model field is empty."""
        return ExecutionSummaryResponse(
            workflow_execution_id=self.execution_id,
            workflow_id=self.workflow_id,
            workflow_name=workflow_name,
            status="queued",
            phase_progress=PhaseProgressInfo.of(
                PhaseProgress(status="queued", completed=0, skipped=0, defined=0)
            ),
            total_tokens=0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_cache_creation_tokens=0,
            total_cache_read_tokens=0,
            start_queue=self.queue,
        )


async def queued_starts(store: ProjectionStoreProtocol) -> list[QueuedStart]:
    """Every start still waiting to open its execution, oldest first (PC-124).

    The same two sources as the detail, merged the same way: each start
    waiting for a slot in this process, with its position; then each direct
    request owed a start that no process here holds, from its durable record.
    A start that holds a slot is ``starting`` rather than queued, and a
    withdrawn one is cancelled, so neither is listed.

    A resume's durable record is keyed by its parent, which the list already
    shows, so an unheld resume is reported on the parent (``resume_start``)
    and not here.
    """
    budget = get_execution_budget()
    found: dict[str, QueuedStart] = {}
    for position in budget.queued():
        claim = position.claim
        record = await _request_record(store, claim.execution_id)
        if record is not None and record.status == "withdrawn":
            continue
        found[claim.execution_id] = QueuedStart(
            execution_id=claim.execution_id,
            workflow_id=claim.workflow_id,
            queue=_info(position, record),
        )
    for record in await _owed_and_unheld(store):
        if record.execution_id not in found:
            found[record.execution_id] = QueuedStart(
                execution_id=record.execution_id,
                workflow_id=record.workflow_id,
                queue=_info(None, record),
            )
    return sorted(found.values(), key=lambda q: q.queue.queued_at)


async def _owed_and_unheld(store: ProjectionStoreProtocol) -> list[ExecutionRequestStartRecord]:
    """Direct requests still owed a start that no process here holds, and not yet started."""
    budget = get_execution_budget()
    owed: list[ExecutionRequestStartRecord] = []
    for status in OWED_STATUSES:
        rows = await store.query(
            ExecutionRequestStartProcessManager.PROJECTION_NAME, filters={"status": status}
        )
        records = [read_start_record(ExecutionRequestStartRecord, row) for row in rows]
        for record in records:
            if record is None or budget.position(record.execution_id) is not None:
                continue  # unreadable, or held here (queued above, or starting)
            # The record lags the execution's stream: a start that opened its
            # execution has a read model, and is listed from that instead.
            if await store.get("workflow_execution_details", record.execution_id) is None:
                owed.append(record)
    return owed


def _info(
    position: StartPosition | None, record: ExecutionRequestStartRecord | None
) -> ExecutionStartQueueInfo:
    info = start_queue_info(position, record)
    assert info is not None  # one of the two is always given
    return info
