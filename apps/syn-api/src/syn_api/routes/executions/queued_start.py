"""What GET /executions/{id} answers for an accepted start with no execution yet (#1557).

Two sources, in order. The execution budget knows where a start held in THIS
process stands - its queue position, or that it holds a slot. The request
start to-do record is durable: it is there after a restart, before any process
holds the start again, and it says how the last attempt went. Neither is a
read model of the execution, which does not exist until its stream opens.
"""

from __future__ import annotations

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

from .models import ExecutionDetailResponse, ExecutionStartQueueInfo

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
